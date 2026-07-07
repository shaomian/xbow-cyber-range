import { useEffect, useRef } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { wsUrl } from "../api/client";

interface Props {
  instanceId: number;
}

export default function TerminalPanel({ instanceId }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<Terminal | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 14,
      fontFamily: "Consolas, Monaco, 'Courier New', monospace",
      theme: { background: "#1e1e1e", foreground: "#d4d4d4" },
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.open(hostRef.current!);
    try {
      fit.fit();
    } catch {
      /* noop */
    }
    termRef.current = term;
    term.writeln(`\x1b[36m正在连接实例 #${instanceId} 的终端...\x1b[0m`);

    const url = wsUrl(`/api/instances/${instanceId}/terminal`);
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.binaryType = "arraybuffer";

    const sendInput = (data: string) => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(new TextEncoder().encode(data));
      }
    };

    const onResize = () => {
      try {
        fit.fit();
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(
            JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows })
          );
        }
      } catch {
        /* noop */
      }
    };

    ws.onopen = () => {
      term.writeln("\x1b[32m已连接\x1b[0m");
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") {
        try {
          const ctl = JSON.parse(ev.data);
          if (ctl.type === "error") {
            term.writeln(`\x1b[31m[错误] ${ctl.message}\x1b[0m`);
          } else if (ctl.type === "ready") {
            term.writeln(`\x1b[36m[命令: ${ctl.command}]\x1b[0m`);
          }
        } catch {
          term.write(ev.data);
        }
      } else if (ev.data instanceof ArrayBuffer) {
        term.write(new TextDecoder().decode(new Uint8Array(ev.data)));
      }
    };
    ws.onerror = () => {
      term.writeln("\x1b[31m[WebSocket 错误]\x1b[0m");
    };
    ws.onclose = () => {
      term.writeln("\x1b[33m[连接已关闭]\x1b[0m");
    };

    const disposable = term.onData(sendInput);
    const resizeObserver = new ResizeObserver(onResize);
    resizeObserver.observe(hostRef.current!);

    return () => {
      disposable.dispose();
      resizeObserver.disconnect();
      ws.close();
      term.dispose();
    };
  }, [instanceId]);

  return (
    <div
      ref={hostRef}
      style={{
        height: "calc(100vh - 260px)",
        minHeight: 360,
        background: "#1e1e1e",
        padding: 8,
        borderRadius: 6,
        overflow: "hidden",
      }}
    />
  );
}
