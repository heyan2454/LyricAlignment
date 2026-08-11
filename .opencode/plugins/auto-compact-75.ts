/**
 * auto-compact-75：上下文使用量达到 75% 时自动触发压缩（opencode 插件）。
 *
 * opencode 内置 `compaction.auto` 只在上下文接近满（limit.input - reserved）时才触发，
 * 且不可配置百分比阈值。本插件在每次 assistant message 更新后估算当前上下文占用比例：
 *   usage = info.tokens.input + info.tokens.cache.read + info.tokens.cache.write
 *   ratio = usage / model.limit.context
 * 当 ratio >= THRESHOLD（默认 0.75）且距上次压缩超过 COOLDOWN_MS 时，通过
 * `client.session.summarize`（v1 压缩端点，服务端会创建 compaction 任务）主动触发压缩。
 *
 * 触发依据与内置 auto-compact 使用同一信号（message 的 token usage），因此语义一致；
 * 只是把触发点从"接近满"提前到"达到 75%"。
 *
 * 事件说明（对齐当前 SDK 的 Event 枚举，见 types.gen.d.ts）：
 * - 不监听 `session.next.step.*`（该事件不属于 SDK server 事件，永远不会触发）；
 *   改为监听 `message.updated`，其 `info` 为 AssistantMessage，自带 providerID/modelID/tokens。
 * - 模型上下文上限先从 client.config.providers() 查询并缓存；查不到（内置模型不在 provider
 *   配置里）时回退读 `/root/.cache/opencode/models.json`（opencode 本地模型目录），两者都无
 *   才跳过（不误触发）。
 * - 压缩后 COOLDOWN_MS 内不重复触发，避免反复请求。
 * - 本插件只负责"提前到 75% 触发"；内置 compaction.auto 仍可保留作为接近满时的兜底。
 */
import { readFileSync } from "node:fs"
import type { Plugin } from "@opencode-ai/plugin"

const THRESHOLD = 0.75
const COOLDOWN_MS = 5 * 60 * 1000
const MODELS_CACHE = "/root/.cache/opencode/models.json"

export const AutoCompact75: Plugin = async ({ client }) => {
  const modelLimits = new Map<string, number>()
  const lastCompact = new Map<string, number>()

  const log = (
    level: "debug" | "info" | "warn" | "error",
    message: string,
    extra?: Record<string, unknown>,
  ): void => {
    client.app
      .log({ body: { service: "auto-compact-75", level, message, extra: extra ?? {} } })
      .catch(() => {})
  }

  const readModelsCache = (providerID: string, modelID: string): number | undefined => {
    try {
      const raw = readFileSync(MODELS_CACHE, "utf8")
      const parsed = JSON.parse(raw) as Record<
        string,
        { models?: Record<string, { limit?: { context?: number } }> }
      >
      return parsed[providerID]?.models?.[modelID]?.limit?.context
    } catch {
      return undefined
    }
  }

  const getModelLimit = async (providerID: string, modelID: string): Promise<number | undefined> => {
    const key = `${providerID}/${modelID}`
    const cached = modelLimits.get(key)
    if (cached !== undefined) return cached
    try {
      const res = await client.config.providers()
      for (const p of res?.providers ?? []) {
        if (p.id !== providerID) continue
        const m = p.models?.[modelID]
        if (m?.limit?.context) {
          modelLimits.set(key, m.limit.context)
          return m.limit.context
        }
      }
    } catch (e) {
      log("warn", `failed to resolve model context limit for ${key}`, { error: String(e) })
    }
    const fallback = readModelsCache(providerID, modelID)
    if (fallback) {
      modelLimits.set(key, fallback)
      return fallback
    }
    log("warn", `model ${key} not found in providers/models cache, skipping auto-compact for it`)
    return undefined
  }

  return {
    event: async ({ event }) => {
      const runtimeEvent = event as unknown as {
        type: string
        properties: Record<string, unknown>
      }
      const props = runtimeEvent.properties ?? {}

      if (runtimeEvent.type !== "message.updated") return
      const info = props.info as
        | {
            sessionID?: string
            role?: string
            providerID?: string
            modelID?: string
            tokens?: { input?: number; cache?: { read?: number; write?: number } }
          }
        | undefined
      if (!info?.sessionID || info.role !== "assistant" || !info.providerID || !info.modelID) return

      const limit = await getModelLimit(info.providerID, info.modelID)
      if (!limit) return

      const usage =
        (info.tokens?.input ?? 0) +
        (info.tokens?.cache?.read ?? 0) +
        (info.tokens?.cache?.write ?? 0)
      if (usage <= 0) return
      const ratio = usage / limit
      if (ratio < THRESHOLD) return

      const now = Date.now()
      const sessionID = info.sessionID
      if (now - (lastCompact.get(sessionID) ?? 0) < COOLDOWN_MS) return
      lastCompact.set(sessionID, now)

      log("info", `context ${(ratio * 100).toFixed(1)}% >= 75%, triggering compaction`, {
        sessionID,
        usage,
        limit,
        ratio,
      })
      client.session
        .summarize({
          path: { id: sessionID },
          body: { providerID: info.providerID, modelID: info.modelID },
        })
        .then(() => log("info", "compaction triggered", { sessionID }))
        .catch((e: unknown) => log("error", `compaction request failed: ${String(e)}`, { sessionID }))
    },
  }
}
