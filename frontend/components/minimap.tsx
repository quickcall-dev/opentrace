"use client";

import { useRef, useEffect, useCallback } from "react";
import type { Message } from "@/lib/types";
import {
  MINIMAP_COLORS,
  COMPACTION_COLOR,
  INTERRUPTION_COLOR,
  COMPACTION_SIG,
  INTERRUPTION_CLAUDE_SIG,
  INTERRUPTION_CODEX_SIG,
} from "@/lib/constants";

interface MinimapProps {
  messages: Message[];
  scrollContainerRef: React.RefObject<HTMLDivElement | null>;
}

interface Block {
  type: string;
  isCompaction: boolean;
  isInterruption: boolean;
  weight: number;
}

function buildBlocks(msgs: Message[]): Block[] {
  const blocks: Block[] = [];
  for (const m of msgs) {
    if (m.msg_type === "progress") continue;
    if (m.msg_type === "tool_call" && !m.content && !m.tool_name) continue;

    const isCompaction =
      m.msg_type === "user" && !!m.content && m.content.startsWith(COMPACTION_SIG);
    const isInterruption =
      (m.msg_type === "tool_result" &&
        !!m.tool_output &&
        m.tool_output.includes(INTERRUPTION_CLAUDE_SIG)) ||
      (m.msg_type === "user" && !!m.content && m.content.startsWith(INTERRUPTION_CODEX_SIG));

    let weight = 1;
    if (m.msg_type === "user" || m.msg_type === "assistant") weight = 2;
    if (m.content && m.content.length > 500) weight = 3;
    if (isInterruption) weight = Math.max(weight, 2);

    blocks.push({ type: m.msg_type, isCompaction, isInterruption, weight });
  }
  return blocks;
}

function drawCanvas(
  canvas: HTMLCanvasElement,
  blocks: Block[],
  width: number,
  height: number,
) {
  const dpr = window.devicePixelRatio || 1;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.style.width = width + "px";
  canvas.style.height = height + "px";

  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);

  const totalWeight = blocks.reduce((s, b) => s + b.weight, 0);
  const gap = 0.5;
  let y = 0;

  for (const block of blocks) {
    const blockH = Math.max(1, (block.weight / totalWeight) * height - gap);

    if (block.isCompaction) {
      const midY = y + blockH / 2;
      ctx.fillStyle = "rgba(245, 158, 11, 0.15)";
      ctx.fillRect(0, y, width, blockH);
      ctx.strokeStyle = COMPACTION_COLOR;
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(0, midY);
      ctx.lineTo(width, midY);
      ctx.stroke();
      ctx.fillStyle = COMPACTION_COLOR;
      ctx.beginPath();
      ctx.moveTo(width / 2, midY - 3);
      ctx.lineTo(width / 2 + 3, midY);
      ctx.lineTo(width / 2, midY + 3);
      ctx.lineTo(width / 2 - 3, midY);
      ctx.closePath();
      ctx.fill();
    } else if (block.isInterruption) {
      const midY = y + blockH / 2;
      ctx.fillStyle = "rgba(239, 68, 68, 0.15)";
      ctx.fillRect(0, y, width, blockH);
      ctx.strokeStyle = INTERRUPTION_COLOR;
      ctx.lineWidth = 2;
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(0, midY);
      ctx.lineTo(width, midY);
      ctx.stroke();
      ctx.fillStyle = INTERRUPTION_COLOR;
      ctx.beginPath();
      ctx.moveTo(width / 2, midY - 3);
      ctx.lineTo(width / 2 + 3, midY);
      ctx.lineTo(width / 2, midY + 3);
      ctx.lineTo(width / 2 - 3, midY);
      ctx.closePath();
      ctx.fill();
    } else {
      ctx.fillStyle = MINIMAP_COLORS[block.type] || "#d1d5db";
      const indent =
        block.type === "tool_call" || block.type === "tool_result" ? 8 : 4;
      const barWidth = width - indent - 4;
      ctx.fillRect(indent, y, barWidth, Math.max(1, blockH - gap));
    }

    y += blockH + gap;
  }
}

export function Minimap({ messages, scrollContainerRef }: MinimapProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const viewportRef = useRef<HTMLDivElement>(null);
  const isDraggingRef = useRef(false);

  const blocks = buildBlocks(messages);

  // Draw canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container || blocks.length === 0) return;

    const width = container.clientWidth;
    const height = container.clientHeight;
    drawCanvas(canvas, blocks, width, height);
  }, [blocks]);

  // Update viewport indicator
  const updateViewport = useCallback(() => {
    const panel = scrollContainerRef.current;
    const viewport = viewportRef.current;
    const container = containerRef.current;
    if (!panel || !viewport || !container) return;

    const scrollH = panel.scrollHeight;
    const clientH = panel.clientHeight;
    const scrollTop = panel.scrollTop;
    const minimapH = container.clientHeight;

    if (scrollH <= clientH) {
      viewport.style.top = "0px";
      viewport.style.height = minimapH + "px";
      return;
    }

    const viewportRatio = clientH / scrollH;
    const scrollRatio = scrollTop / (scrollH - clientH);
    const vpHeight = Math.max(8, viewportRatio * minimapH);
    const vpTop = scrollRatio * (minimapH - vpHeight);

    viewport.style.top = vpTop + "px";
    viewport.style.height = vpHeight + "px";
  }, [scrollContainerRef]);

  // Scroll tracking
  useEffect(() => {
    const panel = scrollContainerRef.current;
    if (!panel) return;
    const handler = () => updateViewport();
    panel.addEventListener("scroll", handler, { passive: true });
    updateViewport();
    return () => panel.removeEventListener("scroll", handler);
  }, [scrollContainerRef, updateViewport]);

  // Click/drag to scroll
  const scrollToPosition = useCallback(
    (clientY: number) => {
      const container = containerRef.current;
      const panel = scrollContainerRef.current;
      if (!container || !panel) return;
      const rect = container.getBoundingClientRect();
      const pct = Math.max(0, Math.min(1, (clientY - rect.top) / rect.height));
      const maxScroll = panel.scrollHeight - panel.clientHeight;
      panel.scrollTop = pct * maxScroll;
    },
    [scrollContainerRef],
  );

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!isDraggingRef.current) return;
      e.preventDefault();
      scrollToPosition(e.clientY);
    };
    const onUp = () => {
      isDraggingRef.current = false;
    };
    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
    return () => {
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    };
  }, [scrollToPosition]);

  if (messages.length < 10) return null;

  return (
    <div
      ref={containerRef}
      className="w-[60px] flex-shrink-0 relative bg-slate-50 border-l border-border cursor-pointer overflow-hidden"
      onMouseDown={(e) => {
        e.preventDefault();
        isDraggingRef.current = true;
        scrollToPosition(e.clientY);
      }}
    >
      <canvas ref={canvasRef} className="w-full h-full block" />
      <div
        ref={viewportRef}
        className="absolute left-0 right-0 bg-foreground/8 border-[1.5px] border-foreground/20 rounded-sm pointer-events-none min-h-[8px] transition-[top,height] duration-[50ms] ease-out"
      />
    </div>
  );
}
