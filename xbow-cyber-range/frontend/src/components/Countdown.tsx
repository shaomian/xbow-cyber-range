import { useEffect, useState } from "react";
import { Tag, Tooltip } from "antd";

interface Props {
  remaining: number | null;
  status: string;
}

function fmt(sec: number): string {
  if (sec <= 0) return "已过期";
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  const parts: string[] = [];
  if (d) parts.push(`${d}天`);
  if (h) parts.push(`${h}时`);
  if (m) parts.push(`${m}分`);
  parts.push(`${s}秒`);
  return parts.join(" ");
}

export default function Countdown({ remaining, status }: Props) {
  const [sec, setSec] = useState<number | null>(remaining);

  useEffect(() => {
    setSec(remaining);
    if (remaining == null || remaining <= 0 || status !== "running") return;
    const t = setInterval(() => {
      setSec((prev) => (prev == null ? prev : Math.max(0, prev - 1)));
    }, 1000);
    return () => clearInterval(t);
  }, [remaining, status]);

  if (sec == null || status === "removed") {
    return <Tag>不过期</Tag>;
  }
  if (sec <= 0) {
    return <Tag color="red">已过期</Tag>;
  }
  const danger = sec < 300;
  const warn = sec < 600;
  const color = danger ? "red" : warn ? "orange" : "green";
  return (
    <Tooltip title="即将到期可点击「续期」延长">
      <Tag color={color} style={{ fontFamily: "monospace" }}>
        {fmt(sec)}
      </Tag>
    </Tooltip>
  );
}
