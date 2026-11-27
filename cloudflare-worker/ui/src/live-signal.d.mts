export function createLiveSignal(onChanged: () => void, url?: string): {
  start(): void
  stop(): void
}
