# GreenGate relay (Cloudflare Worker)

Forwards encrypted blobs between the parent app and the child devices. Protocol: `docs/SPEC.md` §5.
Code: `src/index.ts` (router, stateless), `src/device.ts` (one Durable Object per device, SQLite-backed,
WebSocket hibernation), `src/pairing.ts` (6-digit codes, 10 minutes).

## What it stores

Per device: id, device public key, device token, name, platform, last-seen, parent public keys with
one bearer token each, queued encrypted commands (until acked or expired), encrypted results (until
fetched once, or 600 s). Nothing else. No screenshot, history or setting ever exists in clear here.

## Run locally

```
cd server && npm install
npm run dev            # http://127.0.0.1:8787  (local Miniflare, no account needed)
npm test               # test/e2e.mjs: pairing, offline queue, flush on connect, 600 KB round trips, guards
npm run typecheck
```

## Deploy (once, by the account owner)

```
cd server
npx wrangler login     # opens the browser; Workers free plan is enough (Durable Objects with SQLite are included)
npx wrangler deploy    # prints https://greengate-relay.<account>.workers.dev
```

Custom domain later: add the zone to Cloudflare, then in `wrangler.toml` uncomment `routes` with
`relay.<your-domain>` and `custom_domain = true`, and deploy again. Paste the URL into the parent app
("Thêm máy" > "Relay khác?") and into the agents (`greengate_agent.py pair --relay ...`).

## Implementation notes (v1)

- `POST .../cmd` answers `{cmdId, delivered, online, expiresAt}`; `delivered` means the device acked
  within 3 s. Default TTL: screenshot 600 s, history/refresh 86400 s, others 3600 s, max 7 days.
- A fetched result is deleted together with its command, so the second `GET .../result/:id` says
  `expired`. Unfetched results expire after 600 s (DO alarm).
- Blob limit is 950 000 base64 characters (so a WebSocket frame stays under 1 MiB).
- Server -> device also sends `{t:"stored",cmdId}` after a result is saved and `{t:"error",...}`.
  Device -> server `{"t":"ping"}` gets `{"t":"pong"}` without waking the object (auto-response).
- On reconnect the queue is flushed once; a command delivered less than 10 s ago is not re-sent.
- `X-GreenGate-T` header: `edge`, `recv`, `delivered`, `acked`, `stored`, `done` as epoch ms.
- Rate limit: 60 commands per hour per device. Up to 5 parents per device.
