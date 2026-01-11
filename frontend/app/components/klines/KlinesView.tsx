import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { Card, CardContent, CardHeader, CardTitle } from '../ui/card'
import { Button } from '../ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '../ui/select'
import TradingViewChart from './TradingViewChart'
import AIAnalysisPanel from './AIAnalysisPanel'
import PacmanLoader from '../ui/pacman-loader'

interface KlinesViewProps {
  onAccountUpdated?: () => void
}

interface MarketData {
  symbol: string
  price: number
  oracle_price: number
  change24h: number
  volume24h: number
  percentage24h: number
  open_interest: number
  funding_rate: number
}

interface BackfillTask {
  task_id: number
  symbol: string
  status: string
  progress: number
  total_records: number
  collected_records: number
}

export default function KlinesView({ onAccountUpdated }: KlinesViewProps) {
  const { t } = useTranslation()
  const [selectedSymbol, setSelectedSymbol] = useState<string>('BTC')
  const [selectedPeriod, setSelectedPeriod] = useState<string>('1m')
  const [watchlistSymbols, setWatchlistSymbols] = useState<string[]>([])
  const [marketData, setMarketData] = useState<MarketData[]>([])
  const [currentTask, setCurrentTask] = useState<BackfillTask | null>(null)
  const [loading, setLoading] = useState(false)
  const [isPageVisible, setIsPageVisible] = useState(true)
  const [chartType, setChartType] = useState<'candlestick' | 'line' | 'area'>('candlestick')
  const [selectedIndicators, setSelectedIndicators] = useState<string[]>([])
  const [chartLoading, setChartLoading] = useState(false)
  const [klinesData, setKlinesData] = useState<any[]>([])
  const [indicatorsData, setIndicatorsData] = useState<Record<string, any>>({})
  const [indicatorLoading, setIndicatorLoading] = useState(false)
  const [selectedFlowIndicators, setSelectedFlowIndicators] = useState<string[]>([])

  const marketDataIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const taskCheckIntervalRef = useRef<NodeJS.Timeout | null>(null)

  // 页面可见性监听
  useEffect(() => {
    const handleVisibilityChange = () => {
      setIsPageVisible(!document.hidden)
    }

    document.addEventListener('visibilitychange', handleVisibilityChange)
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange)
  }, [])

  // 获取 watchlist 和初始任务检查
  useEffect(() => {
    fetchWatchlist()
    checkCurrentTask() // 初始检查一次是否有任务
  }, [])

  // 获取市场数据
  useEffect(() => {
    if (watchlistSymbols.length > 0 && isPageVisible) {
      fetchMarketData()
      marketDataIntervalRef.current = setInterval(fetchMarketData, 60000) // 改为60秒
    }

    return () => {
      if (marketDataIntervalRef.current) {
        clearInterval(marketDataIntervalRef.current)
        marketDataIntervalRef.current = null
      }
    }
  }, [watchlistSymbols, isPageVisible])

  // 轮询当前任务状态 - 只在有活动任务时轮询
  useEffect(() => {
    if (isPageVisible && currentTask) {
      taskCheckIntervalRef.current = setInterval(checkCurrentTask, 5000) // 有任务时5秒检查一次
    }

    return () => {
      if (taskCheckIntervalRef.current) {
        clearInterval(taskCheckIntervalRef.current)
        taskCheckIntervalRef.current = null
      }
    }
  }, [isPageVisible, currentTask])

  // 组件卸载时清理所有定时器
  useEffect(() => {
    return () => {
      if (marketDataIntervalRef.current) {
        clearInterval(marketDataIntervalRef.current)
      }
      if (taskCheckIntervalRef.current) {
        clearInterval(taskCheckIntervalRef.current)
      }
    }
  }, [])

  const fetchWatchlist = async () => {
    try {
      const response = await fetch('/api/hyperliquid/symbols/watchlist')
      const data = await response.json()
      const symbols = data.symbols || []
      setWatchlistSymbols(symbols)
      if (symbols.length > 0 && !symbols.includes(selectedSymbol)) {
        setSelectedSymbol(symbols[0])
      }
    } catch (error) {
      console.error('Failed to fetch watchlist:', error)
    }
  }

  const fetchMarketData = async () => {
    try {
      const symbolsParam = watchlistSymbols.join(',')
      if (!symbolsParam) return

      const response = await fetch(`/api/market/prices?symbols=${symbolsParam}`)
      if (!response.ok) return

      const data = await response.json()
      const formattedData = data.map((item: any) => ({
        symbol: item.symbol,
        price: item.price || 0,
        oracle_price: item.oracle_price || 0,
        change24h: item.change24h || 0,
        volume24h: item.volume24h || 0,
        percentage24h: item.percentage24h || 0,
        open_interest: item.open_interest || 0,
        funding_rate: item.funding_rate || 0
      }))
      setMarketData(formattedData)
    } catch (error) {
      console.error('Failed to fetch market data:', error)
    }
  }

  const checkCurrentTask = async () => {
    try {
      const response = await fetch('/api/klines/backfill-tasks')
      const data = await response.json()
      const tasks = data.tasks || []

      // 找到正在运行或等待的任务
      const activeTask = tasks.find((t: BackfillTask) =>
        t.status === 'running' || t.status === 'pending'
      )

      if (activeTask) {
        setCurrentTask(activeTask)
      } else {
        // 检查是否有刚完成的任务需要删除
        const completedTask = tasks.find((t: BackfillTask) => t.status === 'completed')
        if (completedTask && currentTask?.task_id === completedTask.task_id) {
          // 删除已完成的任务
          await fetch(`/api/klines/backfill-tasks/${completedTask.task_id}`, {
            method: 'DELETE'
          }).catch(() => {}) // 忽略删除错误
        }
        setCurrentTask(null)
      }
    } catch (error) {
      console.error('Failed to check task status:', error)
    }
  }

  const handleBackfill = async () => {
    if (!selectedSymbol || loading || currentTask) return

    setLoading(true)
    try {
      const endTime = new Date()
      const startTime = new Date()
      startTime.setDate(startTime.getDate() - 30)

      const response = await fetch('/api/klines/backfill', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          symbols: [selectedSymbol],
          start_time: startTime.toISOString(),
          end_time: endTime.toISOString(),
          period: '1m'
        })
      })

      if (response.ok) {
        // 立即检查任务状态
        setTimeout(checkCurrentTask, 500)
      }
    } catch (error) {
      console.error('Failed to start backfill:', error)
    } finally {
      setLoading(false)
    }
  }

  const getSymbolMarketData = (symbol: string) => {
    return marketData.find(data => data.symbol === symbol)
  }

  const formatCompactNumber = (value: number) => {
    if (!value && value !== 0) return '-'
    const abs = Math.abs(value)
    if (abs >= 1_000_000_000) return `${(value / 1_000_000_000).toFixed(2)}B`
    if (abs >= 1_000_000) return `${(value / 1_000_000).toFixed(2)}M`
    if (abs >= 1_000) return `${(value / 1_000).toFixed(2)}K`
    return value.toLocaleString()
  }

  // 渲染按钮或进度条
  const renderBackfillButton = () => {
    if (currentTask) {
      const progress = currentTask.progress || 0
      const collected = currentTask.collected_records || 0
      const total = currentTask.total_records || 0

      return (
        <div className="w-full space-y-1">
          <div className="relative w-full h-8 bg-muted rounded-md overflow-hidden">
            {/* 进度条背景 */}
            <div
              className="absolute inset-y-0 left-0 bg-primary/80 transition-all duration-300"
              style={{ width: `${progress}%` }}
            />
            {/* 进度文字 */}
            <div className="absolute inset-0 flex items-center justify-center text-xs font-medium">
              <span className={progress > 50 ? 'text-primary-foreground' : 'text-foreground'}>
                {currentTask.symbol} ({collected}/{total}) {progress}%
              </span>
            </div>
          </div>
          <p className="text-xs text-muted-foreground text-center">
            {t('kline.backfillInProgress', 'Backfilling in progress...')}
          </p>
        </div>
      )
    }

    return (
      <div className="space-y-2">
        <Button
          onClick={handleBackfill}
          disabled={loading}
          className="w-full"
          size="sm"
        >
          {loading ? t('kline.starting', 'Starting...') : t('kline.backfillHistorical', 'Backfill Historical Data')}
        </Button>
        <p className="text-xs text-muted-foreground">
          {t('kline.backfillLast30Days', 'Backfill last 30 days of K-line data')}
        </p>
      </div>
    )
  }

  return (
    <div className="flex flex-col md:flex-row h-full w-full gap-4 overflow-hidden pb-16 md:pb-0">
      {/* 左侧 70%：选择区 + 市场数据 + 指标 + K线图 */}
      <div className="flex flex-col flex-1 md:flex-[7] min-w-0 space-y-4 overflow-hidden">
        {/* Mobile: Simplified selector bar */}
        <div className="md:hidden flex items-center gap-2 px-2 py-2 bg-background border-b">
          <Select value={selectedSymbol} onValueChange={setSelectedSymbol}>
            <SelectTrigger className="flex-1 h-9">
              <SelectValue placeholder={t('kline.selectSymbol', 'Select Symbol')} />
            </SelectTrigger>
            <SelectContent>
              {watchlistSymbols.map(symbol => (
                <SelectItem key={symbol} value={symbol}>{symbol}</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Select value={selectedPeriod} onValueChange={setSelectedPeriod}>
            <SelectTrigger className="w-20 h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {['1m','5m','15m','1h','4h','1d'].map(p => (
                <SelectItem key={p} value={p}>{p}</SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Desktop: Full control panel */}
        <div className="hidden md:grid grid-cols-1 lg:grid-cols-6 gap-3 flex-shrink-0">
          {/* Symbol and Period Selection */}
          <Card className="lg:col-span-2">
            <CardContent className="pt-4 space-y-3">
              <div className="flex items-center gap-2">
                <Select value={selectedSymbol} onValueChange={setSelectedSymbol}>
                  <SelectTrigger className="flex-1">
                    <SelectValue placeholder={t('kline.selectSymbol', 'Select Symbol')} />
                  </SelectTrigger>
                  <SelectContent>
                    {watchlistSymbols.map(symbol => (
                      <SelectItem key={symbol} value={symbol}>
                        {symbol}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>

                <Select value={selectedPeriod} onValueChange={setSelectedPeriod}>
                  <SelectTrigger className="w-24 sm:w-28">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="1m">1m</SelectItem>
                    <SelectItem value="3m">3m</SelectItem>
                    <SelectItem value="5m">5m</SelectItem>
                    <SelectItem value="15m">15m</SelectItem>
                    <SelectItem value="30m">30m</SelectItem>
                    <SelectItem value="1h">1h</SelectItem>
                    <SelectItem value="2h">2h</SelectItem>
                    <SelectItem value="4h">4h</SelectItem>
                    <SelectItem value="8h">8h</SelectItem>
                    <SelectItem value="12h">12h</SelectItem>
                    <SelectItem value="1d">1d</SelectItem>
                    <SelectItem value="3d">3d</SelectItem>
                    <SelectItem value="1w">1w</SelectItem>
                    <SelectItem value="1M">1M</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {/* K-line environment warning - always visible */}
              <div className="pt-2 border-t">
                <p className="text-xs text-amber-600 font-medium flex items-center gap-1">
                  <span>⚠️</span>
                  <span>{t('kline.mainnetWarning', 'K-line analysis is only available for Mainnet environment')}</span>
                </p>
              </div>

              {selectedSymbol && renderBackfillButton()}
            </CardContent>
          </Card>

          {/* Market Data */}
          <Card className="lg:col-span-2">
            <CardHeader className="py-2">
              <CardTitle className="text-sm">{t('kline.marketData', 'Market Data')}</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-2">
              {selectedSymbol && (
                <div className="grid grid-cols-3 gap-2">
                  {(() => {
                    const data = getSymbolMarketData(selectedSymbol)
                    return data ? (
                      <>
                        <div>
                          <p className="text-xs text-muted-foreground">{t('kline.markPrice', 'Mark Price')}</p>
                          <p className="text-sm font-semibold">{data.price.toLocaleString()}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">{t('kline.oraclePrice', 'Oracle Price')}</p>
                          <p className="text-sm font-semibold">{data.oracle_price.toLocaleString()}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">{t('kline.change24h', '24h Change')}</p>
                          <p className={`text-sm font-semibold ${data.change24h >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                            {data.percentage24h >= 0 ? "+" : ""}{data.percentage24h.toFixed(2)}%
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">{t('kline.volume24h', '24h Volume')}</p>
                          <p className="text-sm font-semibold">${formatCompactNumber(data.volume24h)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">{t('kline.openInterest', 'Open Interest')}</p>
                          <p className="text-sm font-semibold">${formatCompactNumber(data.open_interest)}</p>
                        </div>
                        <div>
                          <p className="text-xs text-muted-foreground">{t('kline.fundingRate', 'Funding Rate')}</p>
                          <p className="text-sm font-semibold">{(data.funding_rate * 100).toFixed(4)}%</p>
                        </div>
                      </>
                    ) : (
                      <div className="col-span-full text-center text-muted-foreground">
                        <div className="flex items-center justify-center gap-2">
                          <PacmanLoader className="w-12 h-6" />
                          <span className="text-xs">{t('common.loading', 'Loading...')}</span>
                        </div>
                      </div>
                    )
                  })()}
                </div>
              )}
              {/* Market Flow Indicators */}
              <div className="flex items-center gap-2 pt-2 border-t">
                <span className="text-xs text-muted-foreground font-medium">{t('kline.flow', 'Flow')}</span>
                <div className="flex gap-1.5 flex-wrap">
                  {[
                    { key: 'cvd', label: 'CVD' },
                    { key: 'taker_volume', label: 'Taker Vol' },
                    { key: 'oi', label: 'OI' },
                    { key: 'oi_delta', label: 'OI Delta' },
                    { key: 'funding', label: 'Funding' },
                    { key: 'depth_ratio', label: 'Depth(log)' },
                    { key: 'order_imbalance', label: 'Imbalance' }
                  ].map(({ key, label }) => (
                    <button
                      key={key}
                      onClick={() => setSelectedFlowIndicators(prev =>
                        prev.includes(key) ? prev.filter(k => k !== key) : [...prev, key]
                      )}
                      className={`px-2 py-1 text-xs rounded transition-colors ${
                        selectedFlowIndicators.includes(key)
                          ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                          : 'hover:bg-muted border'
                      }`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Technical Indicators */}
          <Card className="lg:col-span-2">
            <CardHeader className="py-3">
              <CardTitle className="text-sm">{t('kline.technicalIndicators', 'Technical Indicators')}</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-1.5">
              {/* Row 1: Trend */}
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-muted-foreground font-medium min-w-[52px]">{t('kline.trend', 'Trend')}</span>
                <div className="flex gap-1 flex-wrap">
                  {['MA5', 'MA10', 'MA20', 'EMA20', 'EMA50', 'EMA100'].map(indicator => (
                    <button
                      key={indicator}
                      onClick={() => {
                        setSelectedIndicators(prev =>
                          prev.includes(indicator)
                            ? prev.filter(i => i !== indicator)
                            : [...prev, indicator]
                        )
                      }}
                      className={`px-1.5 py-0.5 text-[10px] rounded transition-colors min-w-[38px] ${
                        selectedIndicators.includes(indicator)
                          ? 'bg-primary/20 text-primary border border-primary/30'
                          : 'hover:bg-muted border'
                      }`}
                    >
                      {indicator}
                    </button>
                  ))}
                </div>
              </div>

              {/* Row 2: Volume */}
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-muted-foreground font-medium min-w-[52px]">{t('kline.volume', 'Volume')}</span>
                <div className="flex gap-1 flex-wrap">
                  {['VWAP', 'OBV'].map(indicator => (
                    <button
                      key={indicator}
                      onClick={() => {
                        setSelectedIndicators(prev =>
                          prev.includes(indicator)
                            ? prev.filter(i => i !== indicator)
                            : [...prev, indicator]
                        )
                      }}
                      className={`px-1.5 py-0.5 text-[10px] rounded transition-colors min-w-[38px] ${
                        selectedIndicators.includes(indicator)
                          ? 'bg-primary/20 text-primary border border-primary/30'
                          : 'hover:bg-muted border'
                      }`}
                    >
                      {indicator}
                    </button>
                  ))}
                </div>
              </div>

              {/* Row 3: Momentum */}
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-muted-foreground font-medium min-w-[52px]">{t('kline.momentum', 'Momentum')}</span>
                <div className="flex gap-1 flex-wrap">
                  {['RSI14', 'RSI7', 'STOCH', 'MACD'].map(indicator => (
                    <button
                      key={indicator}
                      onClick={() => {
                        setSelectedIndicators(prev =>
                          prev.includes(indicator)
                            ? prev.filter(i => i !== indicator)
                            : [...prev, indicator]
                        )
                      }}
                      className={`px-1.5 py-0.5 text-[10px] rounded transition-colors min-w-[38px] ${
                        selectedIndicators.includes(indicator)
                          ? 'bg-primary/20 text-primary border border-primary/30'
                          : 'hover:bg-muted border'
                      }`}
                    >
                      {indicator}
                    </button>
                  ))}
                </div>
              </div>

              {/* Row 4: Volatility */}
              <div className="flex items-center gap-2">
                <span className="text-[9px] text-muted-foreground font-medium min-w-[52px]">{t('kline.volatility', 'Volatility')}</span>
                <div className="flex gap-1 flex-wrap">
                  {['BOLL', 'ATR14'].map(indicator => (
                    <button
                      key={indicator}
                      onClick={() => {
                        setSelectedIndicators(prev =>
                          prev.includes(indicator)
                            ? prev.filter(i => i !== indicator)
                            : [...prev, indicator]
                        )
                      }}
                      className={`px-1.5 py-0.5 text-[10px] rounded transition-colors min-w-[38px] ${
                        selectedIndicators.includes(indicator)
                          ? 'bg-primary/20 text-primary border border-primary/30'
                          : 'hover:bg-muted border'
                      }`}
                    >
                      {indicator}
                    </button>
                  ))}
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* K-Line Chart Area */}
        <Card className="flex-1 min-h-[300px] md:min-h-[420px] min-w-0 overflow-hidden">
          <CardHeader className="py-2 md:py-3">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 md:gap-3">
                <CardTitle className="text-xs md:text-sm">
                  {selectedSymbol} ({selectedPeriod})
                </CardTitle>
                {chartLoading && (
                  <div className="hidden md:flex items-center gap-2 text-sm text-muted-foreground">
                    <PacmanLoader className="w-12 h-6" />
                    {t('kline.loadingKlineData', 'Loading K-line data...')}
                  </div>
                )}
              </div>
              {/* Chart type selector - hidden on mobile */}
              <div className="hidden md:flex gap-1 bg-background/80 backdrop-blur-sm rounded-md p-1 border">
                <button
                  onClick={() => setChartType('candlestick')}
                  className={`px-2 py-1 text-xs rounded transition-colors ${
                    chartType === 'candlestick'
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-muted'
                  }`}
                >
                  {t('kline.candlestick', 'Candlestick')}
                </button>
                <button
                  onClick={() => setChartType('line')}
                  className={`px-2 py-1 text-xs rounded transition-colors ${
                    chartType === 'line'
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-muted'
                  }`}
                >
                  {t('kline.line', 'Line')}
                </button>
                <button
                  onClick={() => setChartType('area')}
                  className={`px-2 py-1 text-xs rounded transition-colors ${
                    chartType === 'area'
                      ? 'bg-primary text-primary-foreground'
                      : 'hover:bg-muted'
                  }`}
                >
                  {t('kline.area', 'Area')}
                </button>
              </div>
            </div>
          </CardHeader>
            <CardContent className="h-[calc(100%-3rem)] pb-4">
                <TradingViewChart
                  symbol={selectedSymbol}
                  period={selectedPeriod}
                  chartType={chartType}
                  selectedIndicators={selectedIndicators}
                  selectedFlowIndicators={selectedFlowIndicators}
                  onLoadingChange={setChartLoading}
                  onIndicatorLoadingChange={setIndicatorLoading}
                  onDataUpdate={(klines, indicators) => {
                    setKlinesData(klines || [])
                    setIndicatorsData(indicators || {})
                  }}
                />
          </CardContent>
        </Card>
      </div>

      {/* 右侧 30%：AI Analysis 独立列 - Hidden on mobile */}
      <div className="hidden md:flex flex-col flex-[3] min-w-[300px] space-y-4">
        <Card className="flex-1 overflow-hidden">
          <CardHeader className="py-3">
            <CardTitle className="text-sm">{t('kline.aiAnalysis', 'AI Analysis')}</CardTitle>
          </CardHeader>
          <CardContent className="pt-0 h-full overflow-y-auto">
            <AIAnalysisPanel
              symbol={selectedSymbol}
              period={selectedPeriod}
              klines={klinesData}
              indicators={indicatorsData}
              marketData={getSymbolMarketData(selectedSymbol)}
              selectedIndicators={selectedIndicators}
              selectedFlowIndicators={selectedFlowIndicators}
              onAnalysisComplete={() => {}}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
