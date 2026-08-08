/**
 * auto-reconnect：主会话网络失败自动重连（opencode 插件）。
 *
 * 行为：
 * - 监听 `session.error`；仅对可重试错误（ApiError / UnknownError）触发；
 *   MessageAbortedError（用户主动中止）、ProviderAuthError（认证失败）不触发——
 *   避免在无意义场景下反复发请求（离线/认证问题不发）。
 * - 失败后等待 RETRY_DELAY_MS（默认 10 分钟），通过 `/session/{id}/prompt_async`
 *   向该会话重发一条继续提示，自动恢复 agentic loop（未完成事项自动继续）。
 * - 每会话在 RETRY_WINDOW_MS（1 小时）内最多 MAX_RETRIES 次（6 次 ≈ 1 小时），
 *   超过后放弃并 warn 日志，避免无限重发。
 * - 重发本身失败会再调度一轮（退避仍为 RETRY_DELAY_MS）。
 *
 * 子 agent 的超时快速失败由 provider `timeout`/`chunkTimeout`/`headerTimeout`
 * 配置负责（见 opencode.json），本插件只处理主会话层面的断线恢复。
 */
import type { Plugin } from "@opencode-ai/plugin"

const RETRY_DELAY_MS = 10 * 60 * 1000 // 10 分钟重连一次
const MAX_RETRIES_PER_SESSION = 6 // 1 小时窗口上限
const RETRY_WINDOW_MS = 60 * 60 * 1000

const RECONNECT_PROMPT =
  "[auto-reconnect] 网络中断已恢复。若上次任务未完成请继续执行；若已无未完成事项，请简要确认当前状态。"

interface RetryState {
  count: number
  firstAt: number
  timer?: ReturnType<typeof setTimeout>
}

export const AutoReconnect: Plugin = async ({ client }) => {
  const retryState = new Map<string, RetryState>()

  const log = (
    level: "debug" | "info" | "warn" | "error",
    message: string,
    extra?: Record<string, unknown>,
  ): void => {
    client.app
      .log({ body: { service: "auto-reconnect", level, message, extra: extra ?? {} } })
      .catch(() => {})
  }

  const isRetryable = (err: unknown): boolean => {
    if (err == null) return true // 无错误详情时保守重试
    const name = (err as { name?: string })?.name ?? ""
    const type = (err as { type?: string })?.type ?? ""
    return (
      name === "ApiError" ||
      name === "UnknownError" ||
      type === "api_error" ||
      type === "unknown_error"
    )
  }

  const scheduleReconnect = (sessionID: string): void => {
    const now = Date.now()
    let st = retryState.get(sessionID)
    if (!st) {
      st = { count: 0, firstAt: now }
      retryState.set(sessionID, st)
    }
    if (now - st.firstAt > RETRY_WINDOW_MS) {
      st.count = 0
      st.firstAt = now
    }
    if (st.count >= MAX_RETRIES_PER_SESSION) {
      log("warn", `session ${sessionID}: max retries (${MAX_RETRIES_PER_SESSION}) reached in window, giving up`)
      retryState.delete(sessionID)
      return
    }
    st.count += 1
    if (st.timer !== undefined) clearTimeout(st.timer)
    st.timer = setTimeout(() => {
      client.session
        .promptAsync({
          path: { id: sessionID },
          body: { parts: [{ type: "text", text: RECONNECT_PROMPT }] },
        })
        .then(() => {
          log("info", `session ${sessionID}: reconnected (attempt ${st?.count})`)
          retryState.delete(sessionID)
        })
        .catch((e: unknown) => {
          log("error", `session ${sessionID}: reconnect attempt ${st?.count} failed: ${String(e)}`)
          scheduleReconnect(sessionID) // 网络仍未恢复 → 再调度一轮
        })
    }, RETRY_DELAY_MS)
  }

  return {
    event: async ({ event }) => {
      if (event.type !== "session.error") return
      const sid = event.properties?.sessionID
      if (!sid) return
      const err = event.properties?.error
      if (!isRetryable(err)) {
        log("debug", `session ${sid}: non-retryable error skipped: ${String(err)}`)
        return
      }
      log("info", `session ${sid}: scheduling reconnect in ${RETRY_DELAY_MS / 60000} min`)
      scheduleReconnect(sid)
    },
  }
}
