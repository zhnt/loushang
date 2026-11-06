import { act, renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useSessionHistory } from "../src/useSessionHistory";

it("navigates back and forward, drops forward history on a new selection and skips removed Sessions", () => {
  const select = vi.fn();
  const { result, rerender } = renderHook(({ id, available }) => useSessionHistory("context", id, available, select), {
    initialProps: { id: "a", available: { a: {}, b: {}, c: {} } as Record<string, unknown> },
  });
  expect(result.current.onBack).toBeUndefined();
  rerender({ id: "b", available: { a: {}, b: {}, c: {} } });
  act(() => result.current.onBack?.()); expect(select).toHaveBeenLastCalledWith("a");
  rerender({ id: "a", available: { a: {}, b: {}, c: {} } });
  act(() => result.current.onForward?.()); expect(select).toHaveBeenLastCalledWith("b");
  rerender({ id: "b", available: { a: {}, b: {}, c: {} } });
  act(() => result.current.onBack?.());
  rerender({ id: "a", available: { a: {}, b: {}, c: {} } });
  rerender({ id: "c", available: { a: {}, b: {}, c: {} } });
  expect(result.current.onForward).toBeUndefined();
  rerender({ id: "c", available: { c: {} } });
  expect(result.current.onBack).toBeUndefined();
});

it("clears navigation when the application context changes", () => {
  const { result, rerender } = renderHook(({ owner, id }) => useSessionHistory(owner, id, { a: {}, b: {} }, () => {}), { initialProps: { owner: "one", id: "a" } });
  rerender({ owner: "one", id: "b" }); expect(result.current.onBack).toBeDefined();
  rerender({ owner: "two", id: "b" }); expect(result.current.onBack).toBeUndefined();
});
