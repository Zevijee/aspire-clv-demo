import { useAccount } from './context'

/** The account page. Only the signed-in user for now; settings come later. */
export function UserSettings() {
  const { username } = useAccount()
  return (
    <section className="user-settings" aria-labelledby="user-settings-account">
      <h2 id="user-settings-account">Account</h2>
      <dl>
        <div>
          <dt>Username</dt>
          <dd>{username}</dd>
        </div>
      </dl>
    </section>
  )
}
