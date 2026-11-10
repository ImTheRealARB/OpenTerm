# AI web access (opt-in)

By default the AI in OpenTerm cannot reach the internet: it answers from OpenTerm's own data tools. `SETTINGS AI WEB ON` gives it two more tools.
Nothing changes until you turn it on, and `SETTINGS AI WEB OFF` takes them away again.

| Tool | What it does |
|---|---|
| `web_search` | Asks one search provider for up to 8 results (title, URL, snippet). |
| `read_url` | Fetches one public web page (HTML, text, JSON, XML or PDF) and returns its readable text. |

Both only read. No tool can place an order or change a setting, so a hostile page has nothing dangerous to call.

## Turning it on

1. `SETTINGS AI WEB PROVIDER BRAVE|TAVILY|SEARXNG` picks the search provider (default `BRAVE`).
2. Put that provider's key in `APIKEYS` (section "AI web search"): `BRAVE_SEARCH_API_KEY`, `TAVILY_API_KEY`, or `SEARXNG_URL`.
   Without it `web_search` answers `KEY REQUIRED`; `read_url` needs no key.
3. `SETTINGS AI WEB ON`. The setting is also a row in `SETTINGS`.

`TEST` on a key sends one tiny query (Brave and Tavily count it against your allowance).

### SearXNG

Run your own [SearXNG](https://docs.searxng.org/) instance with JSON output enabled (`search.formats: [html, json]` in its `settings.yml`) and put its
address in `SEARXNG_URL`, for example `http://localhost:8080`. You typed that address, so it may be a private one; the model can never choose it.
The page guard below does not apply to the search server, only to pages `read_url` fetches.

## Privacy

- Your **search query text goes to the search provider** (Brave, Tavily, or whatever your SearXNG forwards to). Do not turn this on for questions
  that must not leave your machine. The query is shaped by the model, from your question.
- `read_url` contacts the page's own server, which sees the request from your IP address: a fixed generic User-Agent, no cookies, no referrer, no
  OpenTerm credentials. Cookies a server sets are dropped after every hop.
- Keys are sent only to their provider, never in a URL, never to the frontend, and never in an error message or log.
- Every web call is written to `AUDIT` (hash of the arguments plus the host and path of a page, never its query string; a search shows only
  `search`). With `STORETEXT ON` the redacted question and answer are kept locally as for any AI run.

## Untrusted text

A page is written by a stranger and may contain instructions aimed at the model (prompt injection). Defences:

- Every result sits between `<<<BEGIN UNTRUSTED WEB CONTENT>>>` and `<<<END ...>>>` markers, with the URL and fetch time, and a note that it is data,
  never instructions. Text inside that looks like those markers, a chat role, `<|...|>` tokens or tool-call JSON is rewritten with look-alike
  characters; invisible characters are removed. Hidden HTML (scripts, `display:none`, `aria-hidden`, comments) is not extracted.
- Per answer: at most 5 page reads and 3 searches (more are refused, the run goes on).
- A URL that appeared only inside a fetched page is not fetched unless you typed it, a search listed it, or your question asked to browse or follow links.
- Web text is **not data**. It is never counted as grounding: an answer built only from web pages is labelled `UNGROUNDED`, numbers taken from a page
  are listed as unsourced, and the result rows in the AI panel are marked untrusted with the fetch time. The model is told to label web figures
  with the page they came from.

## The address guard (SSRF)

`read_url` is a way to make this machine open connections, so the URL is checked before every request, on the first hop and on **every redirect**
(at most 5):

1. Only `http` and `https`, no user name or password in the URL, only ports 80 and 443, no spaces or control characters, at most 2,000 characters.
2. IP addresses in any spelling are normalised first (`2130706433`, `0x7f.1`, `0177.0.0.1`, `127.1`, `::ffff:127.0.0.1`) and then judged.
3. Host names such as `localhost`, `*.localhost`, `*.local`, `*.internal`, `*.lan`, `*.home.arpa` and single-label names are refused.
4. The name is resolved **by OpenTerm**, and **every** address in the answer must be public. One private address among public ones refuses the lot.
   Refused ranges: loopback, `0.0.0.0`, private `10/8` `172.16/12` `192.168/16`, link-local `169.254/16` (cloud metadata `169.254.169.254`),
   carrier-grade NAT `100.64/10`, multicast, reserved and documentation ranges, IPv6 loopback, unique local `fc00::/7`, link-local `fe80::/10`, and
   IPv4 hidden in IPv4-mapped, NAT64 and 6to4 addresses.
5. The connection goes to the address that was checked, not to the name (the name is only the `Host` header and the TLS server name), so a DNS answer
   that changes between the check and the connection (DNS rebinding) cannot redirect it.
6. Redirects are followed by hand and each target goes through steps 1 to 5. `https` to `http` is refused. Environment proxies are ignored.
7. Size and time: at most 2 MB is read (a PDF over that is refused, only 25 PDF pages are read), 15 s per request and 30 s in total, and only these
   content types are read: HTML, XHTML, plain text, Markdown, XML, JSON, PDF.

`OPENTERM_REMOTE=1` (self-hosted remote mode) changes nothing about the guard: it does not loosen it, and it is not weaker or stronger there.

### Limits, stated plainly

- The guard blocks what it can recognise from addresses. It cannot judge the content of a public page; that is what the untrusted fencing is for, and
  fencing lowers the risk of prompt injection, it does not remove it. Read what the AI quotes from the web before relying on it.
- A page that is public but hostile can still lie, or try to talk the model into a wrong answer. Web text is not checked for truth.
- Only one machine-local check is made per hop; a network device that rewrites traffic after OpenTerm (a transparent proxy on your network) is outside
  its reach.
- SearXNG and the provider APIs are trusted endpoints you chose; they are not run through the page guard.
- Numbers in a SWARM role's written answer that came from a web page can flow to later roles as that role's notes. Coverage reports mark which roles
  used the web, but cannot separate web-derived sentences inside a role's answer.

## SWARM

With web access OFF, desks whose limits say `NO WEB ACCESS` stay `PARTIAL`. With it ON, the roles named in that limit get `web_search` and
`read_url`, the limit goes, and a desk with no other limits becomes `FULL` (computed from the limits, nothing hard-coded). Desks with other limits
(no code execution, a data source we lack) stay `PARTIAL`. The SWARM result (`swarm_done.web`) lists the roles that used the web, how many web calls
and the URLs, as a separate class labelled untrusted third-party text; `grounded`, `unsourced` and the coverage numbers count OpenTerm's own data only.
