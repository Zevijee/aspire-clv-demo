/** State, portfolio and region from a location row's path, for the
 * Show all facilities table. Missing levels read as empty. */
export function locationPlace(path: readonly { level: string; name: string }[]): readonly [string, string, string] {
  const name = (level: string) => path.find(part => part.level === level)?.name ?? ''
  return [name('state'), name('portfolio'), name('region')]
}
