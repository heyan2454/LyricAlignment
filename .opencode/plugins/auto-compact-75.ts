/**
 * auto-compact-75：上下文使用量达到 75% 时自动触发压缩（opencode 插件）。
 *
 * opencode 内置 `compaction.auto` 只在上下文接近满（limit.input - reserved）时才触发，
 * 且不可配置百分比阈值。本插件在每次 agent step 结束后估算当前上下文占用比例：
 *   usage = step tokens.input + cache.read + cache.write
 *   ratio = usage / model.limit.context
 * 当 ratio >= THRESHOLD（默认 0.75）且距上次压缩超过 COOLDOWN_MS 时，通过
 * `client.session.summarize`（v1 压缩端点，服务端会创建 compaction 任务）主动触发压缩。
 *
 * 触发依据与内置 auto-compact 使用同一信号（step 的 token usage），因此语义一致；
 * 只是把触发点从"接近满"提前到"达到 75%"。
 *
 * 说明：
 * - 每个 session 单独跟踪 model（来自 session.next.step.started），模型上下文上限
 *   从 client.config.providers() 查询并缓存，查不到则跳过（不误触发）。
 * - 压缩后 COOLDOWN_MS 内不重复触发，避免反复请求。
 * - 本插件只负责"提前到 75% 触发"；内置 compaction.auto 仍可保留作为接近满时的兜底。
 */
import type { Plugin } from "@opencode-ai/plugin"

const THRESHOLD = 0.75
const COOLDOWN_MS = 5 * 60 * 1000

export const AutoCompact75: Plugin = async ({ client }) => {
  const modelLimits = new Map<string, number>()
  const sessionModels = new Map<string, { providerID: string; modelID: string }>()
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
      log("warn", `model ${key} not found in providers, skipping auto-compact for it`)
    } catch (e) {
      log("warn", `failed to resolve model context limit for ${key}`, { error: String(e) })
    }
    return undefined
  }

  return {
    event: async ({ event }) => {
      const runtimeEvent = event as unknown as {
        type: string
        properties: Record<string, unknown>
      }
      const props = runtimeEvent.properties ?? {}

      if (runtimeEvent.type === "session.next.step.started") {
        const model = props.model as { providerID?: string; id?: string } | undefined
        const sessionID = props.sessionID as string | undefined
        if (sessionID && model?.providerID && model?.id) {
          sessionModels.set(sessionID, { providerID: model.providerID, modelID: model.id })
        }
        return
      }

      if (runtimeEvent.type !== "session.next.step.ended") return
      const sessionID = props.sessionID as string | undefined
      const tokens = props.tokens as
        | { input?: number; cache?: { read?: number; write?: number } }
        | undefined
      if (!sessionID || !tokens) return

      const model = sessionModels.get(sessionID)
      if (!model) return
      const limit = await getModelLimit(model.providerID, model.modelID)
      if (!limit) return

      const usage = (tokens.input ?? 0) + (tokens.cache?.read ?? 0) + (tokens.cache?.write ?? 0)
      if (usage <= 0) return
      const ratio = usage / limit
      if (ratio < THRESHOLD) return

      const now = Date.now()
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
          body: { providerID: model.providerID, modelID: model.modelID },
        })
        .then(() => log("info", "compaction triggered", { sessionID }))
        .catch((e: unknown) => log("error", `compaction request failed: ${String(e)}`, { sessionID }))
    },
  }
}
