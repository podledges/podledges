import { DurableObject } from "cloudflare:workers";
import {
  applyMove,
  freshState,
  hydrateState,
  isMove,
  normalizeName,
  type GameState,
  type Move,
} from "./game";

export interface Env {
  BLACKJACK_TABLE: DurableObjectNamespace<BlackjackTable>;
  GITHUB_TOKEN?: string;
  GITHUB_REPOSITORY?: string;
}

const TABLE_NAME = "podledges-shared-blackjack";
const DEFAULT_REPOSITORY = "podledges/podledges";
const SYNC_COOLDOWN_MS = 60_000;
const ALLOWED_ORIGIN = "https://podledges.github.io";
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
  "Access-Control-Max-Age": "86400",
  Vary: "Origin",
};

type StateRow = { state: string };
type MetaRow = { value: string };
type MoveRequest = { move: Move; by: string };

function json(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8" },
  });
}

function withCors(response: Response): Response {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(CORS_HEADERS)) headers.set(key, value);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function error(message: string, status: number): Response {
  return json({ error: message }, status);
}

function parseMoveRequest(value: unknown): MoveRequest | Response {
  if (!value || typeof value !== "object" || Array.isArray(value)) return error("body must be a JSON object", 400);
  const body = value as Record<string, unknown>;
  if (!isMove(body.move)) return error("move must be one of deal, hit, stand, walk", 400);
  const by = normalizeName(body.by);
  if (!by) return error("by must be a non-empty name of 20 characters or fewer", 400);
  return { move: body.move, by };
}

export class BlackjackTable extends DurableObject<Env> {
  constructor(ctx: DurableObjectState, env: Env) {
    super(ctx, env);
    ctx.blockConcurrencyWhile(async () => {
      ctx.storage.sql.exec(`
        CREATE TABLE IF NOT EXISTS blackjack_state (
          id INTEGER PRIMARY KEY CHECK (id = 1),
          state TEXT NOT NULL
        )
      `);
      ctx.storage.sql.exec(`
        CREATE TABLE IF NOT EXISTS blackjack_meta (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        )
      `);
      const rows = ctx.storage.sql.exec<StateRow>("SELECT state FROM blackjack_state WHERE id = 1").toArray();
      if (rows.length === 0) {
        ctx.storage.sql.exec("INSERT INTO blackjack_state (id, state) VALUES (1, ?)", JSON.stringify(freshState()));
      }
    });
  }

  private readState(): GameState {
    const rows = this.ctx.storage.sql.exec<StateRow>("SELECT state FROM blackjack_state WHERE id = 1").toArray();
    if (rows.length === 0) {
      const initial = freshState();
      this.writeState(initial);
      return initial;
    }
    try {
      return hydrateState(JSON.parse(rows[0].state));
    } catch {
      const initial = freshState();
      this.writeState(initial);
      return initial;
    }
  }

  private writeState(state: GameState): void {
    this.ctx.storage.sql.exec("UPDATE blackjack_state SET state = ? WHERE id = 1", JSON.stringify(state));
  }

  private requestSync(): void {
    const token = this.env.GITHUB_TOKEN?.trim();
    if (!token) return;

    const repository = this.env.GITHUB_REPOSITORY?.trim() || DEFAULT_REPOSITORY;
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) return;

    const now = Date.now();
    const rows = this.ctx.storage.sql.exec<MetaRow>(
      "SELECT value FROM blackjack_meta WHERE key = 'last-dispatch-at'",
    ).toArray();
    const lastDispatchAt = Number(rows[0]?.value ?? 0);
    if (Number.isFinite(lastDispatchAt) && now - lastDispatchAt < SYNC_COOLDOWN_MS) return;

    this.ctx.storage.sql.exec(
      "INSERT INTO blackjack_meta (key, value) VALUES ('last-dispatch-at', ?) " +
      "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
      String(now),
    );

    const [owner, repo] = repository.split("/");
    const dispatch = fetch(
      `https://api.github.com/repos/${encodeURIComponent(owner)}/${encodeURIComponent(repo)}/dispatches`,
      {
        method: "POST",
        headers: {
          Accept: "application/vnd.github+json",
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
          "User-Agent": "podledges-blackjack-worker",
          "X-GitHub-Api-Version": "2022-11-28",
        },
        body: JSON.stringify({ event_type: "table-sync" }),
      },
    ).then(async (response) => {
      if (!response.ok) console.error(`repository_dispatch failed with HTTP ${response.status}`);
    }).catch((error: unknown) => {
      console.error("repository_dispatch request failed", error instanceof Error ? error.message : String(error));
    });
    this.ctx.waitUntil(dispatch);
  }

  async fetch(request: Request): Promise<Response> {
    const url = new URL(request.url);
    if (request.method === "GET" && url.pathname === "/state") {
      return json(this.readState());
    }
    if (request.method === "POST" && url.pathname === "/move") {
      let parsedBody: unknown;
      try {
        parsedBody = await request.json();
      } catch {
        return error("body must be valid JSON", 400);
      }
      const parsed = parseMoveRequest(parsedBody);
      if (parsed instanceof Response) return parsed;
      const state = this.readState();
      applyMove(state, parsed.move, parsed.by);
      this.writeState(state);
      this.requestSync();
      return json(state);
    }
    if (url.pathname === "/state" || url.pathname === "/move") {
      return error("method not allowed", 405);
    }
    return error("not found", 404);
  }
}

const worker: ExportedHandler<Env> = {
  async fetch(request, env) {
    if (request.method === "OPTIONS") return withCors(new Response(null, { status: 204 }));
    const url = new URL(request.url);
    if (!((request.method === "GET" && url.pathname === "/state") || (request.method === "POST" && url.pathname === "/move"))) {
      return withCors(error("not found", 404));
    }
    const id = env.BLACKJACK_TABLE.idFromName(TABLE_NAME);
    const response = await env.BLACKJACK_TABLE.get(id).fetch(request);
    return withCors(response);
  },
};

export default worker;
