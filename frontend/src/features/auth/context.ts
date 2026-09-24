import { createContext, useContext } from 'react'

export type Account = { username: string; signOut: () => void }

export const AccountContext = createContext<Account | null>(null)

/** The signed-in user. Only rendered inside SignInGate, so it is always set. */
export function useAccount(): Account {
  const account = useContext(AccountContext)
  if (!account) throw new Error('useAccount must be used inside SignInGate.')
  return account
}
