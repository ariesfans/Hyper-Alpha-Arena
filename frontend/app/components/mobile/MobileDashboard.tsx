import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { ChevronDown, Loader2 } from 'lucide-react'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import {
  ArenaPositionsAccount,
  ArenaTrade,
  getArenaPositions,
  getArenaTrades,
  updateArenaPnl,
} from '@/lib/api'
import { useTradingMode } from '@/contexts/TradingModeContext'
import { getModelLogo } from '@/components/portfolio/logoAssets'
import PositionsSection from './MobilePositionsSection'
import TradesSection from './MobileTradesSection'

export default function MobileDashboard() {
  const { t } = useTranslation()
  const { tradingMode } = useTradingMode()
  const [selectedAccount, setSelectedAccount] = useState<number | 'all'>('all')
  const [positions, setPositions] = useState<ArenaPositionsAccount[]>([])
  const [trades, setTrades] = useState<ArenaTrade[]>([])
  const [loading, setLoading] = useState(true)
  const [updatingPnl, setUpdatingPnl] = useState(false)
  const [showPnlConfirm, setShowPnlConfirm] = useState(false)
  const [pnlResult, setPnlResult] = useState<string | null>(null)

  useEffect(() => {
    if (tradingMode === 'testnet' || tradingMode === 'mainnet') {
      loadData()
    }
  }, [tradingMode])

  const loadData = async () => {
    setLoading(true)
    try {
      const [positionsRes, tradesRes] = await Promise.all([
        getArenaPositions({ trading_mode: tradingMode }),
        getArenaTrades({ trading_mode: tradingMode, limit: 50 }),
      ])
      setPositions(positionsRes.accounts || [])
      setTrades(tradesRes.trades || [])
    } catch (error) {
      console.error('Failed to load dashboard data:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleUpdatePnl = async () => {
    setUpdatingPnl(true)
    setPnlResult(null)
    try {
      const result = await updateArenaPnl()
      setPnlResult(result.message || t('feed.pnlUpdated', 'PnL data updated'))
      loadData()
    } catch (error) {
      setPnlResult(t('feed.pnlUpdateFailed', 'Failed to update PnL'))
    } finally {
      setUpdatingPnl(false)
    }
  }

  // Extract account list from positions data
  const accountOptions = positions.map(p => ({ id: p.account_id, name: p.account_name }))

  const filteredPositions = selectedAccount === 'all'
    ? positions
    : positions.filter(p => p.account_id === selectedAccount)

  const filteredTrades = selectedAccount === 'all'
    ? trades
    : trades.filter(t => t.account_id === selectedAccount)

  const selectedAccountName = selectedAccount === 'all'
    ? t('feed.allTraders', 'All Traders')
    : accountOptions.find(a => a.id === selectedAccount)?.name || 'Unknown'

  if (tradingMode !== 'testnet' && tradingMode !== 'mainnet') {
    return (
      <div className="flex items-center justify-center h-full pb-16 text-muted-foreground text-sm">
        {t('dashboard.hyperliquidOnly', 'Only available in Hyperliquid mode')}
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full pb-16">
      <ScrollArea className="flex-1">
        <div className="p-3 space-y-3">
          {/* Filter Dropdown */}
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold uppercase text-muted-foreground">
              {t('feed.accountSummary', 'Account Summary')}
            </span>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" className="h-7 text-xs">
                  {selectedAccountName}
                  <ChevronDown className="ml-1 h-3 w-3" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onClick={() => setSelectedAccount('all')}>
                  {t('feed.allTraders', 'All Traders')}
                </DropdownMenuItem>
                {accountOptions.map(acc => (
                  <DropdownMenuItem key={acc.id} onClick={() => setSelectedAccount(acc.id)}>
                    {acc.name}
                  </DropdownMenuItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
          </div>

          {/* Account Summary Cards - One per Trader */}
          {loading ? (
            <div className="flex items-center justify-center py-4">
              <Loader2 className="h-5 w-5 animate-spin" />
            </div>
          ) : filteredPositions.length === 0 ? (
            <div className="text-xs text-muted-foreground text-center py-4">
              {t('feed.noAccounts', 'No accounts found')}
            </div>
          ) : (
            <div className="space-y-2">
              {filteredPositions.map(account => (
                <AccountSummaryCard key={account.account_id} account={account} />
              ))}
            </div>
          )}

          {/* Positions Section */}
          <PositionsSection positions={filteredPositions} selectedAccount={selectedAccount} loading={loading} />

          {/* Trades Section */}
          <TradesSection
            trades={filteredTrades}
            selectedAccount={selectedAccount}
            loading={loading}
            updatingPnl={updatingPnl}
            showPnlConfirm={showPnlConfirm}
            setShowPnlConfirm={setShowPnlConfirm}
            handleUpdatePnl={handleUpdatePnl}
            pnlResult={pnlResult}
          />
        </div>
      </ScrollArea>
    </div>
  )
}

function AccountSummaryCard({ account }: { account: ArenaPositionsAccount }) {
  const { t } = useTranslation()
  const logo = getModelLogo(account.account_name)
  const marginUsage = account.margin_usage_percent || 0

  return (
    <div className="border rounded-lg bg-card p-3">
      <div className="flex items-center gap-2 mb-2">
        {logo && <img src={logo.src} alt={logo.alt} className="h-5 w-5 rounded-full" />}
        <span className="text-sm font-semibold">{account.account_name}</span>
        {account.environment && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground uppercase">
            {account.environment}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs">
        <div>
          <span className="text-muted-foreground">{t('feed.totalEquity', 'Total Equity')}</span>
          <div className="font-semibold">${account.total_assets?.toFixed(2) || '0.00'}</div>
        </div>
        <div>
          <span className="text-muted-foreground">{t('feed.unrealizedPnl', 'Unrealized PnL')}</span>
          <div className={`font-semibold ${account.total_unrealized_pnl >= 0 ? 'text-emerald-600' : 'text-red-600'}`}>
            ${account.total_unrealized_pnl?.toFixed(2) || '0.00'}
          </div>
        </div>
        <div>
          <span className="text-muted-foreground">{t('feed.availableCash', 'Available Cash')}</span>
          <div className="font-semibold">${account.available_cash?.toFixed(2) || '0.00'}</div>
        </div>
        <div>
          <span className="text-muted-foreground">{t('feed.marginUsage', 'Margin Usage')}</span>
          <div className={`font-semibold ${marginUsage >= 75 ? 'text-red-600' : marginUsage >= 50 ? 'text-amber-600' : 'text-emerald-600'}`}>
            {marginUsage.toFixed(1)}%
          </div>
        </div>
      </div>
    </div>
  )
}
