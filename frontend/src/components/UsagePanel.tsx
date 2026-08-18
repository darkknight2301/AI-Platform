import { useEffect, useState } from "react";
import type { QuotaStatusResponse } from "../api/types";

function formatCountdown(msRemaining: number): string {
  if (msRemaining <= 0) return "00:00:00";
  const totalSeconds = Math.floor(msRemaining / 1000);
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  return [h, m, s].map((n) => String(n).padStart(2, "0")).join(":");
}

function barClass(percent: number): string {
  if (percent >= 90) return "usage-bar-fill danger";
  if (percent >= 70) return "usage-bar-fill warn";
  return "usage-bar-fill";
}

export function UsagePanel({ quota }: { quota: QuotaStatusResponse | null }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  if (!quota) {
    return (
      <div className="sidebar-footer">
        <div className="usage-label">Usage</div>
      </div>
    );
  }

  const { token_quota: tokenQuota, chat_limit: chatLimit } = quota;
  const renewsAtMs = new Date(tokenQuota.renews_at).getTime();
  const countdown = formatCountdown(renewsAtMs - now);
  const tokenPercent = Math.min(100, tokenQuota.percent_used);
  const chatPercent = Math.min(100, chatLimit.percent_used);

  return (
    <div className="sidebar-footer">
      <div className="usage-block">
        <div className="usage-label-row">
          <span className="usage-label">Token usage</span>
          <span className="usage-figure">{tokenPercent.toFixed(0)}%</span>
        </div>
        <div className="usage-bar-track">
          <div className={barClass(tokenPercent)} style={{ width: `${tokenPercent}%` }} />
        </div>
        <div className="usage-sub-row">
          <span>
            {tokenQuota.used_tokens.toLocaleString()} / {tokenQuota.quota_tokens.toLocaleString()}
          </span>
          <span>Renews in {countdown}</span>
        </div>
      </div>

      <div className="usage-block">
        <div className="usage-label-row">
          <span className="usage-label">Active chats</span>
          <span className="usage-figure">
            {chatLimit.active_chats} / {chatLimit.max_active_chats}
          </span>
        </div>
        <div className="usage-bar-track">
          <div className={barClass(chatPercent)} style={{ width: `${chatPercent}%` }} />
        </div>
      </div>
    </div>
  );
}
