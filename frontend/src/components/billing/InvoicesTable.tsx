'use client'

import { Badge } from '@/components/ui/badge'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/common/EmptyState'
import { formatCurrency } from '@/lib/utils/format'
import { formatDate } from '@/lib/utils/time'
import type { Invoice } from '@/types'

/** Hisob-fakturalar — dizayndagi oxirgi jadval. */
const GRID = '1fr 110px 100px 100px'

export function InvoicesTable({ invoices }: { invoices: Invoice[] | undefined }) {
  return (
    <Card className="overflow-hidden">
      <CardHeader>
        <CardTitle className="text-md">Invoices</CardTitle>
      </CardHeader>

      {!invoices || invoices.length === 0 ? (
        <EmptyState
          icon="M4 5a2 2 0 0 1 2-2h9l5 5v11a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2zM14 3v6h6"
          title="No invoices yet"
          description="Your first invoice appears after the current billing period closes."
        />
      ) : (
        <>
          <div className="table-head grid items-center px-4" style={{ gridTemplateColumns: GRID }}>
            <span>Date</span>
            <span className="text-right">Amount</span>
            <span className="text-center">Status</span>
            <span className="text-right">Invoice</span>
          </div>
          {invoices.map((invoice) => (
            <div
              key={invoice.id}
              className="grid h-11 items-center border-b border-line-subtle px-4 last:border-b-0 transition-colors hover:bg-surface-3"
              style={{ gridTemplateColumns: GRID }}
            >
              <span className="text-base text-fg-soft">{formatDate(invoice.date)}</span>
              <span className="tabular text-right font-mono text-base text-fg">
                {formatCurrency(invoice.amount_usd)}
              </span>
              <span className="flex justify-center">
                <Badge variant={invoice.status === 'paid' ? 'success' : 'danger'}>
                  <span
                    className={
                      invoice.status === 'paid'
                        ? 'h-1.5 w-1.5 rounded-full bg-success'
                        : 'h-1.5 w-1.5 rounded-full bg-failed'
                    }
                  />
                  {invoice.status === 'paid' ? 'Paid' : 'Failed'}
                </Badge>
              </span>
              <span className="text-right">
                <a href={invoice.pdf_url} className="text-sm font-medium">
                  Download
                </a>
              </span>
            </div>
          ))}
        </>
      )}
    </Card>
  )
}
