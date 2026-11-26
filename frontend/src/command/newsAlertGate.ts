/**
 * Does THIS browser check news alerts? Only in fixture mode (recorded news); with live news the backend
 * engine checks them with the browser closed. One home for the rule, so the poller can skip the fetch
 * instead of downloading headlines it then throws away (audit M-04).
 */
export function browserChecksNews(engine: { fixtures?: boolean } | null | undefined): boolean {
  return engine?.fixtures === true;
}
