import dayjs from 'dayjs'

/** A Payroll-Based Journal quarter: CMS's federal fiscal quarters, the year
 * starting in October, so October to December is Q1 of the next fiscal year.
 * Each is due the 45th day after it ends. */
export type PbjQuarter = { value: string; label: string; start: string; end: string; due: string }

export const PBJ_QUARTER_PARAM = 'pbj_quarter'
// The first quarter with data: the history starts January 1, 2023.
const FIRST_QUARTER = dayjs('2023-01-01')

function quarter(start: dayjs.Dayjs): PbjQuarter {
  const end = start.add(3, 'month').subtract(1, 'day')
  const fiscalYear = start.month() >= 9 ? start.year() + 1 : start.year()
  const number = Math.floor(((start.month() + 3) % 12) / 3) + 1
  return {
    value: start.format('YYYY-MM-DD'),
    label: `Q${number} FY${fiscalYear} (${start.format('MMM')}–${end.format('MMM YYYY')})`,
    start: start.format('YYYY-MM-DD'),
    end: end.format('YYYY-MM-DD'),
    due: end.add(45, 'day').format('YYYY-MM-DD'),
  }
}

/** Every finished quarter with data, newest first: a PBJ quarter is submitted
 * once it is over. */
export function pbjQuarters(today = dayjs()): PbjQuarter[] {
  const current = today.startOf('month').subtract(today.month() % 3, 'month')
  const quarters: PbjQuarter[] = []
  for (let start = current.subtract(3, 'month'); !start.isBefore(FIRST_QUARTER); start = start.subtract(3, 'month')) {
    quarters.push(quarter(start))
  }
  return quarters
}

/** The quarter in the URL, or the latest finished one. */
export function selectedPbjQuarter(params: URLSearchParams): PbjQuarter {
  const quarters = pbjQuarters()
  return quarters.find(entry => entry.value === params.get(PBJ_QUARTER_PARAM)) ?? quarters[0]
}
