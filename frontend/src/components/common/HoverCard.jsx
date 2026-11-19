import { useState, useRef, useEffect, useCallback, useId } from 'react';
import { createPortal } from 'react-dom';

const DEFAULT_WIDTH = 360;
const GAP = 8; // space between trigger and card
const MARGIN = 8; // minimum distance from the viewport edge
const CLOSE_DELAY_MS = 120; // lets the pointer cross the gap onto the card

/**
 * Wraps its children in a trigger that shows a floating card on hover, keyboard
 * focus, or tap. `renderContent` is only called while the card is open.
 *
 * The card is rendered into document.body with fixed positioning, because the
 * lineup sections use overflow-hidden and would clip a normally-positioned
 * popover. It opens below the trigger when there's room (otherwise above),
 * stays inside the viewport horizontally, and scrolls if taller than the space.
 */
export default function HoverCard({ renderContent, children, className = '', width: preferredWidth = DEFAULT_WIDTH }) {
  const [placement, setPlacement] = useState(null); // null = closed
  const triggerRef = useRef(null);
  const cardRef = useRef(null);
  const closeTimer = useRef(null);
  const cardId = useId();

  const open = useCallback(() => {
    clearTimeout(closeTimer.current);
    const trigger = triggerRef.current;
    if (!trigger) return;

    const rect = trigger.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const width = Math.min(preferredWidth, vw - 2 * MARGIN);
    const left = Math.min(
      Math.max(rect.left + rect.width / 2 - width / 2, MARGIN),
      vw - width - MARGIN
    );
    const spaceBelow = vh - rect.bottom - GAP - MARGIN;
    const spaceAbove = rect.top - GAP - MARGIN;

    setPlacement(
      spaceBelow >= 380 || spaceBelow >= spaceAbove
        ? { left, width, top: rect.bottom + GAP, maxHeight: spaceBelow }
        : { left, width, bottom: vh - rect.top + GAP, maxHeight: spaceAbove }
    );
  }, [preferredWidth]);

  const scheduleClose = useCallback(() => {
    clearTimeout(closeTimer.current);
    closeTimer.current = setTimeout(() => setPlacement(null), CLOSE_DELAY_MS);
  }, []);

  const cancelClose = useCallback(() => clearTimeout(closeTimer.current), []);

  useEffect(() => () => clearTimeout(closeTimer.current), []);

  const isOpen = placement !== null;

  // While open: a tap/click elsewhere, Escape, a page scroll or a resize closes
  // the card. (The card is fixed-position, so it would otherwise drift away
  // from its trigger.) Scrolling inside the card itself is allowed.
  useEffect(() => {
    if (!isOpen) return undefined;

    const close = () => setPlacement(null);
    const onPointerDown = (e) => {
      if (triggerRef.current?.contains(e.target) || cardRef.current?.contains(e.target)) return;
      close();
    };
    const onScroll = (e) => {
      if (!cardRef.current?.contains(e.target)) close();
    };
    const onKeyDown = (e) => {
      if (e.key === 'Escape') close();
    };

    document.addEventListener('pointerdown', onPointerDown);
    document.addEventListener('keydown', onKeyDown);
    window.addEventListener('scroll', onScroll, true);
    window.addEventListener('resize', close);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown);
      document.removeEventListener('keydown', onKeyDown);
      window.removeEventListener('scroll', onScroll, true);
      window.removeEventListener('resize', close);
    };
  }, [isOpen]);

  return (
    <>
      <span
        ref={triggerRef}
        tabIndex={0}
        aria-describedby={isOpen ? cardId : undefined}
        onMouseEnter={open}
        onMouseLeave={scheduleClose}
        onFocus={open}
        onBlur={scheduleClose}
        // Tap on touch screens. Opens only (never toggles shut), so the
        // mouseenter that precedes a tap's click can't immediately undo it.
        onClick={open}
        className={`cursor-help ${className}`}
      >
        {children}
      </span>

      {isOpen &&
        createPortal(
          <div
            ref={cardRef}
            id={cardId}
            role="tooltip"
            onMouseEnter={cancelClose}
            onMouseLeave={scheduleClose}
            style={{
              position: 'fixed',
              left: placement.left,
              width: placement.width,
              top: placement.top,
              bottom: placement.bottom,
              maxHeight: placement.maxHeight,
            }}
            className="z-50 overflow-y-auto rounded-xl border border-sleeper-gray-700 bg-sleeper-darker p-4 shadow-2xl shadow-black/60"
          >
            {renderContent()}
          </div>,
          document.body
        )}
    </>
  );
}
