import { useState, useEffect, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeRaw from 'rehype-raw'
import { toast } from 'react-hot-toast'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import PacmanLoader from '@/components/ui/pacman-loader'
import { TradingAccount } from '@/lib/api'

interface SignalConfig {
  name: string
  symbol: string
  description?: string
  _type?: 'signal' | 'pool'  // Type identifier from backend
  // For single signal
  trigger_condition?: {
    metric: string
    operator?: string
    threshold?: number
    time_window?: string
    direction?: string
    ratio_threshold?: number
    volume_threshold?: number
  }
  // For signal pool
  logic?: 'AND' | 'OR'
  signals?: Array<{
    metric: string
    operator: string
    threshold: number
    time_window?: string
  }>
}

interface AnalysisEntry {
  type: 'reasoning' | 'tool_call' | 'tool_result'
  round?: number
  content?: string
  name?: string
  arguments?: Record<string, unknown>
  result?: Record<string, unknown>
}

interface Message {
  id: number
  role: 'user' | 'assistant'
  content: string
  signal_configs?: SignalConfig[] | null
  isStreaming?: boolean
  statusText?: string
  analysisLog?: AnalysisEntry[]
}

interface Conversation {
  id: number
  title: string
  created_at: string
  updated_at: string
}

interface AiSignalChatModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onCreateSignal: (config: SignalConfig) => Promise<boolean>  // Returns true on success
  onCreatePool: (config: SignalConfig) => Promise<boolean>    // Create signal pool
  onPreviewSignal: (config: SignalConfig) => void
  accounts: TradingAccount[]
  accountsLoading: boolean
}

// Component implementation continues below
export default function AiSignalChatModal({
  open,
  onOpenChange,
  onCreateSignal,
  onCreatePool,
  onPreviewSignal,
  accounts,
  accountsLoading,
}: AiSignalChatModalProps) {
  const [selectedAccountId, setSelectedAccountId] = useState<number | null>(null)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [loadingConversations, setLoadingConversations] = useState(false)
  const [currentConversationId, setCurrentConversationId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [userInput, setUserInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [allSignalConfigs, setAllSignalConfigs] = useState<SignalConfig[]>([])

  // Filter AI accounts
  const aiAccounts = accounts.filter(acc => acc.account_type === 'AI')

  const messagesEndRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (messagesEndRef.current) {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' })
    }
  }, [messages])

  // Load conversations when modal opens and select default AI account
  useEffect(() => {
    if (open) {
      loadConversations()
      // Select first AI account by default
      if (aiAccounts.length > 0 && !selectedAccountId) {
        setSelectedAccountId(aiAccounts[0].id)
      }
    }
  }, [open, accounts])

  // Load messages when conversation changes
  useEffect(() => {
    if (currentConversationId) {
      loadMessages(currentConversationId)
    }
  }, [currentConversationId])

  const loadConversations = async () => {
    setLoadingConversations(true)
    try {
      const response = await fetch('/api/signals/ai-conversations')
      if (response.ok) {
        const data = await response.json()
        setConversations(data.conversations || [])
      }
    } catch (error) {
      console.error('Failed to load conversations:', error)
    } finally {
      setLoadingConversations(false)
    }
  }

  const loadMessages = async (conversationId: number) => {
    try {
      const response = await fetch(`/api/signals/ai-conversations/${conversationId}/messages`)
      if (response.ok) {
        const data = await response.json()
        setMessages(data.messages || [])
        // Collect all signal configs from messages
        const configs: SignalConfig[] = []
        data.messages.forEach((m: Message) => {
          if (m.role === 'assistant' && m.signal_configs) {
            configs.push(...m.signal_configs)
          }
        })
        setAllSignalConfigs(configs)
      }
    } catch (error) {
      console.error('Failed to load messages:', error)
    }
  }

  const sendMessage = async () => {
    if (!userInput.trim() || !selectedAccountId) return
    const userMessage = userInput.trim()
    setUserInput('')
    setLoading(true)

    const tempUserMsgId = Date.now()
    const tempAssistantMsgId = tempUserMsgId + 1
    const tempUserMsg: Message = { id: tempUserMsgId, role: 'user', content: userMessage }
    const tempAssistantMsg: Message = {
      id: tempAssistantMsgId,
      role: 'assistant',
      content: '',
      isStreaming: true,
      statusText: 'Connecting...',
    }
    setMessages(prev => [...prev, tempUserMsg, tempAssistantMsg])

    try {
      const response = await fetch('/api/signals/ai-chat-stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          accountId: selectedAccountId,
          userMessage: userMessage,
          conversationId: currentConversationId,
        }),
      })

      if (!response.ok) throw new Error('Failed to send message')
      if (!response.body) throw new Error('No response body')

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let finalContent = ''
      let finalSignalConfigs: SignalConfig[] = []
      let finalConversationId: number | null = null
      let finalMessageId: number | null = null

      let currentEventType = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            currentEventType = line.slice(7).trim()
            continue
          }
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6))
              handleSSEEvent(currentEventType, data, tempAssistantMsgId, (updates) => {
                if (updates.content !== undefined) finalContent = updates.content
                if (updates.signalConfigs) finalSignalConfigs = updates.signalConfigs
                if (updates.conversationId) finalConversationId = updates.conversationId
                if (updates.messageId) finalMessageId = updates.messageId
              })
            } catch {}
            currentEventType = ''
          }
        }
      }

      // Finalize the message
      setMessages(prev => prev.map(m =>
        m.id === tempAssistantMsgId
          ? { ...m, content: finalContent, signal_configs: finalSignalConfigs, isStreaming: false, statusText: undefined }
          : m
      ))
      if (finalSignalConfigs.length > 0) {
        setAllSignalConfigs(prev => [...prev, ...finalSignalConfigs])
      }
      if (!currentConversationId && finalConversationId) {
        setCurrentConversationId(finalConversationId)
        loadConversations()
      }
    } catch (error) {
      console.error('Error sending message:', error)
      toast.error('Failed to send message')
      setMessages(prev => prev.filter(m => m.id !== tempUserMsgId && m.id !== tempAssistantMsgId))
    } finally {
      setLoading(false)
    }
  }

  const handleSSEEvent = (
    eventType: string,
    data: Record<string, unknown>,
    msgId: number,
    onUpdate: (updates: { content?: string; signalConfigs?: SignalConfig[]; conversationId?: number; messageId?: number }) => void
  ) => {
    if (eventType === 'status') {
      setMessages(prev => prev.map(m =>
        m.id === msgId ? { ...m, statusText: data.message as string } : m
      ))
    } else if (eventType === 'reasoning') {
      const reasoning = data.content as string || ''
      const entry: AnalysisEntry = { type: 'reasoning', content: reasoning }
      setMessages(prev => prev.map(m =>
        m.id === msgId ? {
          ...m,
          statusText: `Thinking: ${reasoning.slice(0, 80)}...`,
          analysisLog: [...(m.analysisLog || []), entry]
        } : m
      ))
    } else if (eventType === 'content') {
      const content = data.content as string
      onUpdate({ content })
      setMessages(prev => prev.map(m =>
        m.id === msgId ? { ...m, content, statusText: undefined } : m
      ))
    } else if (eventType === 'signal_config') {
      const config = data.config as SignalConfig
      if (config) {
        onUpdate({ signalConfigs: [config] })
      }
    } else if (eventType === 'done') {
      const content = data.content as string
      const signalConfigs = data.signal_configs as SignalConfig[]
      onUpdate({
        conversationId: data.conversation_id as number,
        messageId: data.message_id as number,
        content: content,
        signalConfigs: signalConfigs,
      })
    } else if (eventType === 'error') {
      toast.error(data.message as string || 'AI generation failed')
    } else if (eventType === 'tool_call') {
      const entry: AnalysisEntry = {
        type: 'tool_call',
        name: data.name as string,
        arguments: data.arguments as Record<string, unknown>
      }
      setMessages(prev => prev.map(m =>
        m.id === msgId ? {
          ...m,
          statusText: `Calling ${data.name}...`,
          analysisLog: [...(m.analysisLog || []), entry]
        } : m
      ))
    } else if (eventType === 'tool_result') {
      const entry: AnalysisEntry = {
        type: 'tool_result',
        name: data.name as string,
        result: data.result as Record<string, unknown>
      }
      setMessages(prev => prev.map(m =>
        m.id === msgId ? {
          ...m,
          statusText: `Got result from ${data.name}`,
          analysisLog: [...(m.analysisLog || []), entry]
        } : m
      ))
    }
  }

  const startNewConversation = () => {
    setCurrentConversationId(null)
    setMessages([])
    setAllSignalConfigs([])
  }

  const getMetricLabel = (metric: string) => {
    const labels: Record<string, string> = {
      oi: 'Open Interest',
      oi_delta_percent: 'OI Delta %',
      cvd: 'CVD',
      funding_rate: 'Funding Rate',
      depth_ratio: 'Depth Ratio',
      order_imbalance: 'Order Imbalance',
      taker_buy_ratio: 'Taker Buy Ratio',
      taker_volume: 'Taker Volume',
    }
    return labels[metric] || metric
  }

  const getOperatorLabel = (op: string) => {
    const labels: Record<string, string> = {
      greater_than: '>',
      less_than: '<',
      greater_than_or_equal: '>=',
      less_than_or_equal: '<=',
      abs_greater_than: 'abs >',
    }
    return labels[op] || op
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="w-[95vw] max-w-[1400px] h-[85vh] flex flex-col p-0"
        onInteractOutside={(e) => e.preventDefault()}
      >
        <DialogHeader className="px-6 py-4 border-b">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <DialogTitle>AI Signal Generator</DialogTitle>
              <span className="text-xs text-muted-foreground">
                (Requires Function Call support to invoke analysis tools. Reasoning models work best.)
              </span>
            </div>
            {(loadingConversations || accountsLoading) && <PacmanLoader className="w-8 h-4" />}
          </div>
          <div className="flex items-center gap-4 mt-4">
            <div className="flex-1">
              <label className="text-xs text-muted-foreground mb-1 block">AI Trader</label>
              <Select
                value={selectedAccountId?.toString()}
                onValueChange={(val) => setSelectedAccountId(parseInt(val))}
                disabled={accountsLoading}
              >
                <SelectTrigger>
                  <SelectValue placeholder={accountsLoading ? "Loading..." : "Select AI Trader"} />
                </SelectTrigger>
                <SelectContent>
                  {aiAccounts.map(acc => (
                    <SelectItem key={acc.id} value={acc.id.toString()}>
                      {acc.name} ({acc.model})
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1">
              <label className="text-xs text-muted-foreground mb-1 block">Conversation</label>
              <div className="flex gap-2">
                <Select
                  value={currentConversationId?.toString() || 'new'}
                  onValueChange={(val) => {
                    if (val === 'new') startNewConversation()
                    else setCurrentConversationId(parseInt(val))
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="New Conversation" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="new">New Conversation</SelectItem>
                    {conversations.map(conv => (
                      <SelectItem key={conv.id} value={conv.id.toString()}>
                        {conv.title}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button variant="outline" size="sm" onClick={startNewConversation}>New</Button>
              </div>
            </div>
          </div>
        </DialogHeader>

        <div className="flex-1 flex overflow-hidden">
          {/* Left: Chat Area (45%) */}
          <ChatArea
            messages={messages}
            userInput={userInput}
            setUserInput={setUserInput}
            loading={loading}
            sendMessage={sendMessage}
            messagesEndRef={messagesEndRef}
            hasAccount={!!selectedAccountId}
          />

          {/* Right: Signal Cards (55%) */}
          <SignalCardsPanel
            configs={allSignalConfigs}
            onPreview={onPreviewSignal}
            onCreate={onCreateSignal}
            onCreatePool={onCreatePool}
            getMetricLabel={getMetricLabel}
            getOperatorLabel={getOperatorLabel}
          />
        </div>
      </DialogContent>
    </Dialog>
  )
}

// Chat Area Component
function ChatArea({
  messages, userInput, setUserInput, loading, sendMessage, messagesEndRef, hasAccount
}: {
  messages: Message[]
  userInput: string
  setUserInput: (v: string) => void
  loading: boolean
  sendMessage: () => void
  messagesEndRef: React.RefObject<HTMLDivElement>
  hasAccount: boolean
}) {
  return (
    <div className="w-[45%] flex flex-col border-r">
      <ScrollArea className="flex-1 p-4">
        <div className="space-y-4">
          {messages.length === 0 && (
            <div className="text-center text-muted-foreground py-8">
              <p className="text-sm">Describe the signal you want to create</p>
              <p className="text-xs mt-2">Example: "Create a signal for BTC when OI increases by 1%"</p>
            </div>
          )}
          {messages.map((msg) => (
            <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-lg p-3 ${
                msg.role === 'user' ? 'bg-primary text-white' : 'bg-muted'
              }`}>
                <div className={`text-xs font-semibold mb-1 ${msg.role === 'user' ? 'text-white/70' : 'opacity-70'}`}>
                  {msg.role === 'user' ? 'You' : 'AI Assistant'}
                  {msg.isStreaming && msg.statusText && (
                    <span className="ml-2 text-primary animate-pulse">({msg.statusText})</span>
                  )}
                </div>
                {/* Show analysis log during streaming */}
                {msg.isStreaming && msg.analysisLog && msg.analysisLog.length > 0 && (
                  <div className="mb-2 text-xs bg-background/50 rounded p-2 max-h-32 overflow-y-auto">
                    {msg.analysisLog.slice(-5).map((entry, idx) => (
                      <div key={idx} className="mb-1 last:mb-0">
                        {entry.type === 'tool_call' && (
                          <span className="text-blue-500">→ {entry.name}({Object.entries(entry.arguments || {}).map(([k,v]) => `${k}=${v}`).join(', ')})</span>
                        )}
                        {entry.type === 'tool_result' && (
                          <span className="text-green-500">← {entry.name}: {JSON.stringify(entry.result).slice(0, 80)}...</span>
                        )}
                        {entry.type === 'reasoning' && (
                          <span className="text-gray-500 italic">{(entry.content || '').slice(0, 100)}...</span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
                <div className={`text-sm prose prose-sm max-w-none ${
                  msg.role === 'user' ? 'prose-invert text-white' : 'dark:prose-invert'
                } [&_details]:bg-muted/50 [&_details]:rounded-lg [&_details]:p-2 [&_details]:mb-3 [&_details]:text-xs [&_summary]:cursor-pointer [&_summary]:font-medium [&_summary]:text-muted-foreground [&_details>div]:mt-2 [&_details>div]:max-h-64 [&_details>div]:overflow-y-auto [&_details>div]:whitespace-pre-wrap [&_details>div]:text-muted-foreground`}>
                  {msg.content ? (
                    <ReactMarkdown rehypePlugins={[rehypeRaw]}>{msg.content}</ReactMarkdown>
                  ) : msg.isStreaming ? (
                    <span className="text-muted-foreground italic">Generating...</span>
                  ) : null}
                </div>
              </div>
            </div>
          ))}
          <div ref={messagesEndRef} />
        </div>
      </ScrollArea>
      <div className="p-4 border-t">
        <div className="flex gap-2 items-end">
          <textarea
            placeholder="Describe your signal..."
            value={userInput}
            onChange={(e) => setUserInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                sendMessage()
              }
            }}
            disabled={loading || !hasAccount}
            className="flex-1 min-h-[80px] rounded-md border px-3 py-2 text-sm resize-y"
            rows={3}
          />
          <Button onClick={sendMessage} disabled={loading || !userInput.trim() || !hasAccount} className="h-[80px]">
            {loading ? 'Sending...' : 'Send'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// Signal Cards Panel Component
function SignalCardsPanel({
  configs, onPreview, onCreate, onCreatePool, getMetricLabel, getOperatorLabel
}: {
  configs: SignalConfig[]
  onPreview: (config: SignalConfig) => void
  onCreate: (config: SignalConfig) => Promise<boolean>
  onCreatePool: (config: SignalConfig) => Promise<boolean>
  getMetricLabel: (m: string) => string
  getOperatorLabel: (o: string) => string
}) {
  // Track which signals/pools are being created and which have been created
  const [creatingSignals, setCreatingSignals] = useState<Set<string>>(new Set())
  const [createdSignals, setCreatedSignals] = useState<Set<string>>(new Set())

  const handleCreate = async (config: SignalConfig, isPool: boolean) => {
    const signalKey = config.name || `signal-${configs.indexOf(config)}`
    setCreatingSignals(prev => new Set(prev).add(signalKey))
    try {
      const success = isPool ? await onCreatePool(config) : await onCreate(config)
      if (success) {
        setCreatedSignals(prev => new Set(prev).add(signalKey))
      }
    } finally {
      setCreatingSignals(prev => {
        const next = new Set(prev)
        next.delete(signalKey)
        return next
      })
    }
  }

  return (
    <div className="w-[55%] flex flex-col bg-muted/30">
      <div className="p-4 border-b">
        <h3 className="text-sm font-semibold">Generated Signals</h3>
        <p className="text-xs text-muted-foreground mt-1">
          {configs.length > 0
            ? `${configs.length} signal${configs.length > 1 ? 's' : ''} generated`
            : 'AI-generated signals will appear here'}
        </p>
      </div>
      <ScrollArea className="flex-1 p-4">
        {configs.length > 0 ? (
          <div className="space-y-4">
            {configs.map((config, idx) => {
              const signalKey = config.name || `signal-${idx}`
              const isPool = config._type === 'pool'
              return isPool ? (
                <SignalPoolCard
                  key={idx}
                  config={config}
                  onCreate={() => handleCreate(config, true)}
                  getMetricLabel={getMetricLabel}
                  getOperatorLabel={getOperatorLabel}
                  isCreating={creatingSignals.has(signalKey)}
                  isCreated={createdSignals.has(signalKey)}
                />
              ) : (
                <SignalCard
                  key={idx}
                  config={config}
                  onPreview={() => onPreview(config)}
                  onCreate={() => handleCreate(config, false)}
                  getMetricLabel={getMetricLabel}
                  getOperatorLabel={getOperatorLabel}
                  isCreating={creatingSignals.has(signalKey)}
                  isCreated={createdSignals.has(signalKey)}
                />
              )
            })}
          </div>
        ) : (
          <div className="flex items-center justify-center h-full text-muted-foreground">
            <div className="text-center">
              <p className="text-sm">No signals generated yet</p>
              <p className="text-xs mt-2">Start a conversation to generate signals</p>
            </div>
          </div>
        )}
      </ScrollArea>
    </div>
  )
}

// Individual Signal Card Component
function SignalCard({
  config, onPreview, onCreate, getMetricLabel, getOperatorLabel, isCreating, isCreated
}: {
  config: SignalConfig
  onPreview: () => void
  onCreate: () => void
  getMetricLabel: (m: string) => string
  getOperatorLabel: (o: string) => string
  isCreating?: boolean
  isCreated?: boolean
}) {
  const cond = config.trigger_condition || {}
  const isTakerVolume = cond.metric === 'taker_volume'
  const hasValidMetric = cond.metric && typeof cond.metric === 'string'

  // Check if signal config is valid
  const isValid = hasValidMetric && (
    isTakerVolume || (cond.operator && cond.threshold !== undefined)
  )

  return (
    <div className={`rounded-lg border bg-card p-4 ${!isValid ? 'border-destructive/50' : ''}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h4 className="font-semibold text-sm">{config.name || 'Unnamed Signal'}</h4>
          <p className="text-xs text-muted-foreground">{config.symbol || 'No symbol'}</p>
        </div>
        {hasValidMetric ? (
          <span className="text-xs bg-primary/10 text-primary px-2 py-1 rounded">
            {getMetricLabel(cond.metric)}
          </span>
        ) : (
          <span className="text-xs bg-destructive/10 text-destructive px-2 py-1 rounded">
            Invalid Config
          </span>
        )}
      </div>
      {config.description && (
        <p className="text-xs text-muted-foreground mb-3">{config.description}</p>
      )}
      <div className="bg-muted/50 rounded p-2 mb-3">
        <div className="text-xs space-y-1">
          {!hasValidMetric ? (
            <div className="text-destructive">Missing metric configuration</div>
          ) : isTakerVolume ? (
            <>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Direction:</span>
                <span>{cond.direction || 'any'}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Ratio Threshold:</span>
                <span>{cond.ratio_threshold || 1.5}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Volume Threshold:</span>
                <span>{cond.volume_threshold || 0}</span>
              </div>
            </>
          ) : (
            <>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Metric:</span>
                <span>{getMetricLabel(cond.metric)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Condition:</span>
                <span>{getOperatorLabel(cond.operator || '')} {cond.threshold}</span>
              </div>
            </>
          )}
          <div className="flex justify-between">
            <span className="text-muted-foreground">Time Window:</span>
            <span>{cond.time_window || '5m'}</span>
          </div>
        </div>
      </div>
      <div className="flex gap-2">
        <Button variant="outline" size="sm" className="flex-1" onClick={onPreview} disabled={!isValid}>
          Preview
        </Button>
        {isCreated ? (
          <Button size="sm" className="flex-1" variant="secondary" disabled>
            <span className="text-green-600">✓ Created</span>
          </Button>
        ) : (
          <Button size="sm" className="flex-1" onClick={onCreate} disabled={!isValid || isCreating}>
            {isCreating ? 'Creating...' : 'Create Signal'}
          </Button>
        )}
      </div>
    </div>
  )
}

// Signal Pool Card Component
function SignalPoolCard({
  config, onCreate, getMetricLabel, getOperatorLabel, isCreating, isCreated
}: {
  config: SignalConfig
  onCreate: () => void
  getMetricLabel: (m: string) => string
  getOperatorLabel: (o: string) => string
  isCreating?: boolean
  isCreated?: boolean
}) {
  const signals = config.signals || []
  const isValid = signals.length > 0 && signals.every(s => s.metric && s.operator && s.threshold !== undefined)

  return (
    <div className={`rounded-lg border bg-card p-4 ${!isValid ? 'border-destructive/50' : 'border-primary/50'}`}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <h4 className="font-semibold text-sm">{config.name || 'Unnamed Pool'}</h4>
          <p className="text-xs text-muted-foreground">{config.symbol || 'No symbol'}</p>
        </div>
        <span className="text-xs bg-primary/20 text-primary px-2 py-1 rounded font-medium">
          Pool ({config.logic || 'AND'})
        </span>
      </div>
      {config.description && (
        <p className="text-xs text-muted-foreground mb-3">{config.description}</p>
      )}
      <div className="bg-muted/50 rounded p-2 mb-3">
        <div className="text-xs font-medium mb-2">
          {signals.length} Signal{signals.length > 1 ? 's' : ''} Combined with {config.logic || 'AND'}:
        </div>
        <div className="space-y-1">
          {signals.map((sig, idx) => (
            <div key={idx} className="text-xs flex items-center gap-2 bg-background/50 rounded px-2 py-1">
              <span className="font-medium">{getMetricLabel(sig.metric)}</span>
              <span className="text-muted-foreground">
                {getOperatorLabel(sig.operator)} {sig.threshold}
              </span>
              <span className="text-muted-foreground">({sig.time_window || '5m'})</span>
            </div>
          ))}
        </div>
      </div>
      <div className="flex gap-2">
        {isCreated ? (
          <Button size="sm" className="flex-1" variant="secondary" disabled>
            <span className="text-green-600">✓ Pool Created</span>
          </Button>
        ) : (
          <Button size="sm" className="flex-1" onClick={onCreate} disabled={!isValid || isCreating}>
            {isCreating ? 'Creating...' : 'Create Signal Pool'}
          </Button>
        )}
      </div>
    </div>
  )
}
