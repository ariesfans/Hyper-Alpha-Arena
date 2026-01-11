/**
 * HyperliquidView - Hyperliquid Trading Mode Main View
 *
 * ARCHITECTURE:
 * - This component is the ACTIVE container for Hyperliquid mode (testnet/mainnet)
 * - Uses HyperliquidAssetChart for asset curve visualization with multi-account support
 * - Uses HyperliquidMultiAccountSummary for multi-account summary display
 * - Uses AlphaArenaFeed for real-time trading feed
 *
 * DO NOT CONFUSE WITH:
 * - ComprehensiveView: Legacy paper trading component (deprecated, kept for reference)
 * - AssetCurveWithData: Paper mode chart component (NOT used here)
 *
 * CURRENT STATUS: Active production component for multi-wallet Hyperliquid architecture
 */
import React, { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { useTradingMode } from '@/contexts/TradingModeContext'
import { getArenaPositions, getArenaTrades, ArenaTrade } from '@/lib/api'
import AlphaArenaFeed from '@/components/portfolio/AlphaArenaFeed'
import HyperliquidMultiAccountSummary from '@/components/portfolio/HyperliquidMultiAccountSummary'
import HyperliquidAssetChart, { TradeMarker } from './HyperliquidAssetChart'

interface HyperliquidViewProps {
  wsRef?: React.MutableRefObject<WebSocket | null>
  refreshKey?: number
  onPageChange?: (page: string) => void
}

export default function HyperliquidView({ wsRef, refreshKey = 0, onPageChange }: HyperliquidViewProps) {
  const { t } = useTranslation()
  const { tradingMode } = useTradingMode()
  const [loading, setLoading] = useState(true)
  const [positionsData, setPositionsData] = useState<any>(null)
  const [chartRefreshKey, setChartRefreshKey] = useState(0)
  const [selectedAccount, setSelectedAccount] = useState<number | 'all'>('all')
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null)
  const [tradeMarkers, setTradeMarkers] = useState<TradeMarker[]>([])
  const environment = tradingMode === 'testnet' || tradingMode === 'mainnet' ? tradingMode : undefined

  // Load data from APIs
  useEffect(() => {
    const loadData = async () => {
      try {
        setLoading(true)
        const [positions, tradesRes] = await Promise.all([
          getArenaPositions({ trading_mode: tradingMode }),
          getArenaTrades({ trading_mode: tradingMode, limit: 200 })
        ])
        setPositionsData(positions)
        // Convert trades to TradeMarker format
        const markers: TradeMarker[] = (tradesRes.trades || []).map((t: ArenaTrade) => ({
          trade_id: t.trade_id,
          trade_time: t.trade_time || '',
          side: t.side,
          symbol: t.symbol,
          account_id: t.account_id,
          price: t.price
        }))
        setTradeMarkers(markers)
      } catch (error) {
        console.error('Failed to load Hyperliquid data:', error)
      } finally {
        setChartRefreshKey(prev => prev + 1)
        setLoading(false)
      }
    }

    loadData()
  }, [tradingMode, refreshKey])

  // Extract account list for multi-account summary
  const accounts = positionsData?.accounts?.map((acc: any) => ({
    account_id: acc.account_id,
    account_name: acc.account_name,
  })) || []

  // Extract all positions with account_id for the summary component
  const allPositions = positionsData?.accounts?.flatMap((acc: any) =>
    (acc.positions || []).map((pos: any) => ({
      symbol: pos.symbol,
      side: pos.side,
      size: pos.quantity,
      entry_price: pos.avg_cost,
      mark_price: pos.current_price,
      unrealized_pnl: pos.unrealized_pnl,
      leverage: pos.leverage || 1,
      account_id: acc.account_id,
    }))
  ) || []

  const firstAccountId = accounts[0]?.account_id

  if (loading && !positionsData) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-muted-foreground">{t('dashboard.loadingData', 'Loading Hyperliquid data...')}</div>
      </div>
    )
  }

  return (
    <div className="flex flex-col md:grid md:gap-6 md:grid-cols-5 h-full min-h-0 gap-4 pb-16 md:pb-0 overflow-y-auto md:overflow-hidden">
      {/* Left Panel - Chart & Account Summary */}
      <div className="md:col-span-3 flex flex-col gap-4 min-h-0">
        <div className="flex-1 min-h-[250px] md:min-h-[320px]">
          {positionsData?.accounts?.length > 0 ? (
            <HyperliquidAssetChart
              accountId={firstAccountId}
              refreshTrigger={chartRefreshKey}
              environment={environment}
              selectedAccount={selectedAccount}
              trades={tradeMarkers}
              selectedSymbol={selectedSymbol}
            />
          ) : (
            <div className="bg-card border border-border rounded-lg h-full flex items-center justify-center">
              <div className="text-muted-foreground">{t('dashboard.noAccountConfigured', 'No Hyperliquid account configured')}</div>
            </div>
          )}
        </div>
        <div className="border text-card-foreground shadow p-4 md:p-6 space-y-4 md:space-y-6">
          <HyperliquidMultiAccountSummary
            accounts={accounts}
            refreshKey={refreshKey + chartRefreshKey}
            selectedAccount={selectedAccount}
            positions={allPositions}
          />
        </div>
      </div>

      {/* Right Panel - Feed (hidden on mobile) */}
      <div className="hidden md:flex md:col-span-2 flex-col min-h-0">
        <div className="flex-1 min-h-0 border border-border rounded-lg bg-card shadow-sm px-4 py-3 flex flex-col">
          <AlphaArenaFeed
            wsRef={wsRef}
            selectedAccount={selectedAccount}
            onSelectedAccountChange={setSelectedAccount}
            onSelectedSymbolChange={setSelectedSymbol}
            onPageChange={onPageChange}
          />
        </div>
      </div>
    </div>
  )
}
