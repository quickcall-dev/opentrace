"use client";

import React, {
  useRef,
  useState,
  useEffect,
  useCallback,
  type ReactNode,
} from "react";
import { SlideIndicator, type SlideGroup } from "./slide-indicator";
import { cn } from "@/lib/utils";

interface SlideContainerProps {
  children: ReactNode;
  groups?: SlideGroup[];
  className?: string;
}

export function SlideContainer({
  children,
  groups,
  className,
}: SlideContainerProps) {
  const slideCount = React.Children.count(children);
  const [activeSlide, setActiveSlide] = useState(0);
  const isAnimating = useRef(false);
  const touchStartY = useRef(0);
  const innerRefs = useRef<(HTMLDivElement | null)[]>([]);
  const boundaryHits = useRef(0);

  const goToSlide = useCallback(
    (index: number) => {
      const clamped = Math.max(0, Math.min(index, slideCount - 1));
      if (clamped === activeSlide) return;
      isAnimating.current = true;
      boundaryHits.current = 0;
      setActiveSlide(clamped);
      history.replaceState(null, "", `#slide-${clamped + 1}`);
      setTimeout(() => {
        isAnimating.current = false;
        const el = innerRefs.current[clamped];
        if (el) el.scrollTop = 0;
      }, 550);
    },
    [activeSlide, slideCount]
  );

  const canScrollInner = useCallback(
    (direction: "up" | "down") => {
      const el = innerRefs.current[activeSlide];
      if (!el) return false;
      if (direction === "down")
        return el.scrollTop + el.clientHeight < el.scrollHeight - 4;
      return el.scrollTop > 4;
    },
    [activeSlide]
  );

  // Wheel navigation — require 2 consecutive boundary hits before changing slide
  useEffect(() => {
    let cooldown = false;
    const handleWheel = (e: WheelEvent) => {
      if (cooldown || isAnimating.current) return;

      const goingDown = e.deltaY > 0;
      const goingUp = e.deltaY < 0;

      if (
        (goingDown && canScrollInner("down")) ||
        (goingUp && canScrollInner("up"))
      ) {
        boundaryHits.current = 0;
        return;
      }

      e.preventDefault();
      if (Math.abs(e.deltaY) < 20) return;

      boundaryHits.current++;
      if (boundaryHits.current < 2) return;

      cooldown = true;
      boundaryHits.current = 0;
      setTimeout(() => {
        cooldown = false;
      }, 700);

      if (goingDown) goToSlide(activeSlide + 1);
      else if (goingUp) goToSlide(activeSlide - 1);
    };
    window.addEventListener("wheel", handleWheel, { passive: false });
    return () => window.removeEventListener("wheel", handleWheel);
  }, [activeSlide, goToSlide, canScrollInner]);

  // Touch navigation
  useEffect(() => {
    const handleTouchStart = (e: TouchEvent) => {
      touchStartY.current = e.touches[0].clientY;
    };
    const handleTouchEnd = (e: TouchEvent) => {
      if (isAnimating.current) return;
      const delta = touchStartY.current - e.changedTouches[0].clientY;
      if (Math.abs(delta) < 50) return;
      const goingDown = delta > 0;
      if (
        (goingDown && canScrollInner("down")) ||
        (!goingDown && canScrollInner("up"))
      )
        return;
      goToSlide(goingDown ? activeSlide + 1 : activeSlide - 1);
    };
    window.addEventListener("touchstart", handleTouchStart, { passive: true });
    window.addEventListener("touchend", handleTouchEnd, { passive: true });
    return () => {
      window.removeEventListener("touchstart", handleTouchStart);
      window.removeEventListener("touchend", handleTouchEnd);
    };
  }, [activeSlide, goToSlide, canScrollInner]);

  // Keyboard navigation
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if (
        e.key === "ArrowDown" ||
        e.key === " " ||
        e.key === "PageDown"
      ) {
        if (canScrollInner("down")) return;
        e.preventDefault();
        goToSlide(activeSlide + 1);
      } else if (e.key === "ArrowUp" || e.key === "PageUp") {
        if (canScrollInner("up")) return;
        e.preventDefault();
        goToSlide(activeSlide - 1);
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [activeSlide, goToSlide, canScrollInner]);

  // Hash on load
  useEffect(() => {
    const match = window.location.hash.match(/^#slide-(\d+)$/);
    if (match) setActiveSlide(Math.max(0, parseInt(match[1], 10) - 1));
  }, []);

  return (
    <>
      <SlideIndicator
        total={slideCount}
        active={activeSlide}
        onNavigate={goToSlide}
        groups={groups}
      />
      <div
        className={cn(
          "fixed inset-0 overflow-hidden",
          className
        )}
      >
        <div
          className="h-full transition-transform duration-500 ease-in-out"
          style={{ transform: `translateY(-${activeSlide * 100}dvh)` }}
        >
          {React.Children.map(children, (child, i) => (
            <div key={i} className="h-dvh w-full">
              <div
                className="h-full w-full overflow-y-auto"
                ref={(el) => {
                  innerRefs.current[i] = el;
                }}
              >
                {child}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="fixed bottom-4 right-6 z-50 pointer-events-none opacity-35 text-sm font-semibold tracking-wide">
        <span className="text-accent">quick</span>
        <span className="text-slate-800 dark:text-slate-200">call</span>
      </div>
    </>
  );
}
