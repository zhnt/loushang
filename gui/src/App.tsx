import { i18n } from "./i18n";
import { appName } from "./branding";
import { useTranslation } from "react-i18next";
import { ContextMenuProvider, useContextMenu } from "./ContextMenu";
import { CopyButton } from "./CopyButton";
import { AccountMenu } from "./AccountMenu";
import { SettingsDialog } from "./SettingsDialog";
import { Fragment, useEffect, useId, useLayoutEffect, useMemo, useReducer, useRef, useState, type ReactNode } from "react";
import "./App.css";
import type { OfflineAccount } from "./client/offlineAccount";
import { MessageComposer } from "./MessageComposer";
import { GoalProgress } from "./GoalProgress";
import { InteractiveGoalRecovery } from "./InteractiveGoalRecovery";
import { InteractiveGoal } from "./InteractiveGoal";
import { GoalStart, useGoalStart } from "./GoalStart";
import { ToolApproval } from "./ToolApproval";
import { ChoiceReceipt, submittedChoiceLabel, UserChoiceCard, type ChoiceAnswer } from "./UserChoiceCard";
import { ModelPicker } from "./ModelPicker";
import { ReviewNotice } from "./WorkspaceReview";
import { OpenWorkspacePath, WorkspaceInspection, type Inspection } from "./WorkspaceInspection";
import { MessageMarkdown } from "./markdown/MessageMarkdown";
import type { FileReference } from "./markdown/fileReference";
import { WorkspacePreviewDialog } from "./WorkspacePreviewDialog";
import { readMarkdownPreferences } from "./markdown/preferences";
import { DraftChatRow, ProjectNavigation, type SidebarDraft } from "./ProjectNavigation";
import { TEMPORARY_WORKSPACE, workspaceName, type ManagedProjectNavigation, type ProjectNavigationProps } from "./client/projectDirectory";
import { UiIcon } from "./UiIcon";
import { DesktopFrame, PanelIcon } from "./DesktopFrame";
import { readLayoutPreferences, saveLayoutPreferences } from "./layoutPreferences";
import { isTauri } from "@tauri-apps/api/core";
import { useSessionHistory } from "./useSessionHistory";
import { canSubmitDraft, isSendingDraft, useSessionCreation } from "./useSessionCreation";
import { useDraftModels } from "./useDraftModels";
import { readSidebarPreferences, saveSidebarPreferences, updateSidebarPreferences, sidebarPreferencesKey } from "./client/sidebarPreferences";
import { liveSelectionKey, rememberSessionSelection, restoreSessionSelection } from "./client/sessionSelection";
import { createNativeLiveClient } from "./client/nativeLiveClient";
import { probeFixtureBridge, type BridgeProbe } from "./client/nativeFixtureBridge";
import type {
  AgentRunProjection,
  ChangeSetProjection,
  ConversationMessage,
  ClientEvent,
  ClientSnapshot,
  ConnectionState,
  FixturePlaybackPort,
  HarnessClientUiPort,
  ReadonlyDocument,
  RunProjection,
  SessionSnapshot,
  SessionModels,
  ThinkingLevel,
  TaskProjection,
  WorkspaceSummary,
} from "./client/model";
import { emptyGuiState, guiReducer, hasCapability, type DockTab, type GuiState } from "./client/state";

type NoticeKey = `notice.${keyof typeof import("./i18n/locales/en-US/session.json")["notice"]}`;

function copyableReplies(messages: readonly ConversationMessage[], waiting: boolean) {
  const copies = new Map<string, string>();
  let reply: ConversationMessage[] = [];
  function finish() {
    const last = reply[reply.length - 1];
    if (last && reply.every((message) => message.phase === "complete")) {
      copies.set(last.id, reply.map((message) => message.content).join("\n\n"));
    }
    reply = [];
  }
  for (const message of messages) {
    if (message.role === "assistant" && message.content.trim()) reply.push(message);
    if (message.role === "user" && !submittedChoiceLabel(message.content)) finish();
  }
  if (!waiting) finish();
  return copies;
}
type Notice =
  | { key: Exclude<NoticeKey, "notice.rejected" | "notice.interruptReason" | "notice.playback" | "notice.modelChanged"> }
  | { key: "notice.rejected" | "notice.interruptReason"; params: { reason: string } }
  | { key: "notice.playback"; params: { label: string } }
  | { key: "notice.modelChanged"; params: { model: string } };

function NoticeText({ notice }: { notice: Notice }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  switch (notice.key) {
    case "notice.rejected":
    case "notice.interruptReason": return <>{t(notice.key)}{notice.params.reason ? <span> {t("session:diagnostic.details")}: <code>{notice.params.reason}</code></span> : null}</>;
    case "notice.playback": return t(notice.key, notice.params);
    case "notice.modelChanged": return t(notice.key, notice.params);
    default: return t(notice.key);
  }
}

type ManagedHostConnection =
  | { readonly status: "connecting" | "disconnected" }
  | { readonly status: "running"; readonly serviceInstanceId?: string };

interface HarnessGuiProps {
  readonly client: HarnessClientUiPort | FixturePlaybackPort | null;
  readonly account?: OfflineAccount | null;
  readonly hostSettings?: ReactNode;
  readonly startLocalHost?: ReactNode;
  readonly projectNavigation?: ManagedProjectNavigation;
  readonly hostSettingsRequest?: number;
  readonly managedHostConnection?: ManagedHostConnection;
  readonly onConnectionChange?: (connection: ConnectionState | "connecting") => void;
}

const offlineClient: HarnessClientUiPort = {
  snapshot: async () => ({
    generation: "",
    connection: "disconnected",
    source: emptyGuiState().remote.source,
    capabilities: [],
    workspaces: [],
    sessions: [],
    recentSessionIds: [],
    selectedSessionId: "",
  }),
  subscribe: () => () => {},
  submitText: async ({ submissionId }) => ({ submissionId, accepted: false }),
  interrupt: async () => ({ accepted: false }),
};

function fixturePlayback(client: HarnessClientUiPort): FixturePlaybackPort | null {
  return "advanceFixture" in client && "remainingFixtureSteps" in client
    ? client as FixturePlaybackPort
    : null;
}

const dockTabs = [
  { id: "environment", label: "workspace:environment.title" },
  { id: "tasks", label: "panels:dock.tasks" },
  { id: "agents", label: "panels:dock.agents" },
  { id: "review", label: "panels:changes.review" },
] as const;

interface FirstMessagePreview {
  readonly continuityId?: string;
  readonly text: string;
  readonly executionId?: string;
}

function waitingForFirstReply(session: SessionSnapshot, preview: FirstMessagePreview) {
  const execution = session.execution;
  const finished = execution && (!preview.executionId || execution.id === preview.executionId)
    && ["succeeded", "failed", "interrupted"].includes(execution.status);
  return !finished && !session.messages.some((message) => message.role === "assistant" && message.content);
}

export function HarnessGui({ client: attachedClient, account, hostSettings, startLocalHost, hostSettingsRequest = 0, managedHostConnection, onConnectionChange, projectNavigation }: HarnessGuiProps) {
  const client = attachedClient ?? offlineClient;
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const fixture = fixturePlayback(client);
  const native = isTauri();
  const { t: shellText } = useTranslation("shell");
  const [markdown, setMarkdown] = useState(readMarkdownPreferences);
  const settingsDialog = useRef<HTMLDialogElement>(null);
  function openSettings() {
    const dialog = settingsDialog.current;
    if (dialog && !dialog.open) dialog.showModal();
  }
  useEffect(() => { if (hostSettingsRequest > 0) openSettings(); }, [hostSettingsRequest]);
  const [sidebarOpen, setSidebarOpen] = useState(() => readLayoutPreferences().sidebarOpen);
  const previousSidebarOpen = useRef(sidebarOpen);
  useEffect(() => {
    if (previousSidebarOpen.current !== sidebarOpen) {
      document.querySelector<HTMLButtonElement>(sidebarOpen ? ".brand-actions .frame-icon" : ".collapsed-rail .frame-icon")?.focus({ preventScroll: true });
      saveLayoutPreferences({ sidebarOpen });
      previousSidebarOpen.current = sidebarOpen;
    }
  }, [sidebarOpen]);
  const [sidebarWidth, setSidebarWidth] = useState(280);
  const [viewportWidth, setViewportWidth] = useState(window.innerWidth);
  const [transcriptScrollbar, setTranscriptScrollbar] = useState(0);
  const transcriptPosition = useRef<number | null>(null);
  useEffect(() => {
    const resize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", resize);
    return () => window.removeEventListener("resize", resize);
  }, []);
  const sidebarDrag = useRef<{ x: number; width: number } | null>(null);
  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.ctrlKey && !event.altKey && !event.shiftKey && !event.isComposing && !event.repeat && event.key.toLowerCase() === "b") {
        event.preventDefault(); setSidebarOpen((open) => !open);
      }
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, []);
  const [state, dispatch] = useReducer(guiReducer, undefined, emptyGuiState);
  const [notice, setNotice] = useState<Notice>({ key: "notice.loading" });
  const [operationFailures, setOperationFailures] = useState<Record<string, {
    notice: Notice; pending?: { id: string; text: string; instanceId?: string };
  }>>({});
  const [syncing, setSyncing] = useState(true);
  const [installedClient, setInstalledClient] = useState<HarnessClientUiPort | null>(null);
  const refreshRef = useRef<(() => void) | null>(null);
  const syncPendingRef = useRef(true);
  const [remainingSteps, setRemainingSteps] = useState(fixture?.remainingFixtureSteps() ?? 0);
  const [controlPending, setControlPending] = useState<"submit" | "interrupt" | null>(null);
  const [modelResult, setModelResult] = useState<{ scope: string; query: string; models: SessionModels | null } | null>(null);
  const modelRequest = useRef(0);
  const [modelPending, setModelPending] = useState(false);
  const [goalBusyScope, setGoalBusyScope] = useState<string | null>(null);
  const controlPendingRef = useRef(false);
  const [publications, setPublications] = useState<Readonly<Record<string, {
    readonly source: ClientSnapshot["source"];
    readonly cursor: string;
    readonly executionId?: string;
    readonly draftText?: string;
  }>>>({});
  const [choiceAnswers, setChoiceAnswers] = useState<Readonly<Record<string, ChoiceAnswer>>>({});
  const [firstMessages, setFirstMessages] = useState<Readonly<Record<string, FirstMessagePreview>>>({});
  const draftCreation = useSessionCreation(({ session, snapshot }, text, receipt, select) => {
    setFirstMessages((current) => ({
      ...current, [session.id]: { continuityId: session.context.continuityId, text, executionId: receipt.executionId },
    }));
    if (select) dispatch({ type: "session.selected", sessionId: session.id });
    if (receipt.executionId) setPublications((current) => ({
      ...current,
      [session.id]: { source: snapshot.source, cursor: session.cursor, executionId: receipt.executionId, draftText: text },
    }));
    setNotice({ key: "notice.liveAccepted" });
  });
  const observeDraft = draftCreation.observe;
  const draftHost = projectNavigation?.hostKey ?? "native";
  const hideDraft = draftCreation.hide;
  useEffect(() => { hideDraft(); }, [draftHost, hideDraft]);
  const draft = draftCreation.draft?.visible && draftCreation.draft.target.hostKey === draftHost
    ? draftCreation.draft : null;
  const [draftFocus, setDraftFocus] = useState(0);
  const draftId = draft?.id;
  useLayoutEffect(() => {
    if (draftId) document.getElementById("message-input")?.focus();
  }, [draftId, draftFocus]);
  const [bridgeProbe, setBridgeProbe] = useState<BridgeProbe>({
    status: "web-mock",
    label: "Web Mock",
  });
  const submissionCounter = useRef(1);
  const transcriptRef = useRef<HTMLDivElement | null>(null);
  const quickLookTriggerRef = useRef<HTMLButtonElement | null>(null);
  const restoreQuickLookFocusRef = useRef(false);

  useEffect(() => {
    let active = true;
    let pending = false;
    let buffered: ClientEvent[] = [];
    let overflow = false;
    let latestSnapshot: ClientSnapshot | null = null;
    function install(snapshot: ClientSnapshot, fallbackNotice: Notice) {
      dispatch({ type: "snapshot.installed", snapshot: restoreSessionSelection(snapshot) });
      setInstalledClient(client);
      observeDraft(client, snapshot);
      setNotice(fallbackNotice);
    }
    async function refresh(): Promise<void> {
      if (!active || pending) return;
      pending = true;
      syncPendingRef.current = true;
      buffered = [];
      overflow = false;
      latestSnapshot = null;
      setSyncing(true);
      try {
        const snapshot = await client.snapshot();
        if (snapshot.source.kind === "live") {
          await updateSidebarPreferences(sidebarPreferencesKey(snapshot.source)).catch(() => {});
        }
        if (!active) return;
        if (overflow) throw new Error("Snapshot event buffer exceeded its limit.");
        install(latestSnapshot ?? snapshot, snapshot.source.kind === "fixture"
          ? { key: "notice.fixtureReady" }
          : { key: "notice.liveReady" });
        // The reducer ignores cursors already covered by the snapshot and freezes
        // on any remaining gap. Never infer continuity from arrival timing.
        for (const event of buffered) dispatch({ type: "event.received", event });
        setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
      } catch {
        if (active) dispatch({
          type: "sync.failed",
          message: fixture
            ? "Fixture synchronization failed. Retry to load a fresh snapshot."
            : "Live snapshot synchronization failed. Restart the native connection.",
        });
      } finally {
        if (active) {
          buffered = [];
          pending = false;
          syncPendingRef.current = false;
          setSyncing(false);
        }
      }
    }
    refreshRef.current = () => { void refresh(); };
    const unsubscribe = client.subscribe((event) => {
      if (!active) return;
      if (pending) {
        if (buffered.length < 2048) buffered.push(event);
        else overflow = true;
      } else dispatch({ type: "event.received", event });
      setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
    });
    const unsubscribeSnapshots = client.subscribeSnapshots?.((snapshot) => {
      if (!active) return;
      latestSnapshot = snapshot;
      install(snapshot, { key: "notice.liveUpdated" });
      setSyncing(false);
    }) ?? (() => undefined);
    const unsubscribeConnection = client.subscribeConnection?.((connection) => {
      if (!active) return;
      observeDraft(client, null);
      dispatch({
        type: "connection.changed",
        connection,
        message: connection === "disconnected"
          ? "Live AppHost disconnected. Reconnecting from a fresh snapshot."
          : "Live event continuity was lost. Requesting a fresh snapshot.",
      });
      setSyncing(true);
    }) ?? (() => undefined);
    void refresh();
    if (fixture) void probeFixtureBridge().then((probe) => {
      if (active) setBridgeProbe(probe);
    });
    return () => {
      active = false;
      observeDraft(client, null);
      refreshRef.current = null;
      unsubscribe();
      unsubscribeSnapshots();
      unsubscribeConnection();
    };
  }, [client, observeDraft, fixture]);

  const resyncRequestedRef = useRef(false);
  useEffect(() => {
    if (state.remote.connection !== "resync-required") {
      resyncRequestedRef.current = false;
      return;
    }
    if (!client.requestResync || resyncRequestedRef.current) return;
    resyncRequestedRef.current = true;
    void client.requestResync().catch(() => {
      dispatch({
        type: "connection.changed",
        connection: "disconnected",
        message: "Unable to request live resynchronization.",
      });
    });
  }, [client, state.remote.connection]);

  useEffect(() => {
    if (!state.local.quickLookDocumentId && restoreQuickLookFocusRef.current) {
      restoreQuickLookFocusRef.current = false;
      quickLookTriggerRef.current?.focus();
    }
  }, [state.local.quickLookDocumentId]);

  const requestedSelection = projectNavigation?.selection;
  const appliedSelection = useRef<typeof requestedSelection>(null);
  const [knownTitles, setKnownTitles] = useState<Readonly<Record<string, string>>>({});
  const directoryHost = state.remote.source.kind === "live" ? state.remote.source.connectionId : undefined;
  const liveTitles = useMemo(() => {
    if (state.remote.source.kind !== "live") return {};
    return Object.fromEntries(Object.values(state.remote.sessions).map((session) => {
      const preview = firstMessages[session.id];
      const title = session.title === "New Session" && preview?.continuityId === session.context.continuityId && preview
        ? firstPromptTitle(preview.text) : session.title;
      return [session.id, title];
    }));
  }, [state.remote.source.kind, state.remote.sessions, firstMessages]);
  useEffect(() => { setKnownTitles({}); }, [directoryHost]);
  useEffect(() => {
    if (!projectNavigation) return;
    setKnownTitles((previous) => Object.entries(liveTitles).every(([id, title]) => previous[id] === title)
      ? previous : { ...previous, ...liveTitles });
  }, [Boolean(projectNavigation), liveTitles]);
  useLayoutEffect(() => {
    const id = requestedSelection?.id;
    if (!id || appliedSelection.current === requestedSelection || installedClient !== client
      || !state.remote.sessions[id]) return;
    appliedSelection.current = requestedSelection;
    dispatch({ type: "session.selected", sessionId: id });
  }, [client, installedClient, requestedSelection, state.remote.sessions]);

  const selectedId = state.local.selectedSessionId;
  const selectionReady = !requestedSelection?.id || appliedSelection.current === requestedSelection
    || requestedSelection.id === selectedId;
  const selectionKey = liveSelectionKey(state.remote.source);
  const expectedInstance = managedHostConnection?.status === "running" ? managedHostConnection.serviceInstanceId : undefined;
  const awaitingHostSnapshot = expectedInstance && attachedClient
    && (state.remote.source.kind !== "live" || state.remote.source.serviceInstanceId !== expectedInstance);
  const connection = managedHostConnection && managedHostConnection.status !== "running" ? managedHostConnection.status
    : (attachedClient && !fixture && syncing) || awaitingHostSnapshot ? "connecting" : state.remote.connection;
  // The verified Host stays connected while a draft opens or attaches its Workspace view.
  const draftHostConnected = draft && managedHostConnection?.status === "running" && !state.diagnostic
    && (state.remote.source.kind !== "live" || !expectedInstance || state.remote.source.serviceInstanceId === expectedInstance);
  const displayedConnection = draftHostConnected ? "connected" : connection;
  const liveConnecting = connection === "connecting";
  const connected = installedClient === client && connection === "connected";
  useEffect(() => {
    onConnectionChange?.(displayedConnection);
  }, [displayedConnection, onConnectionChange]);
  useEffect(() => {
    if (connected && selectionKey && selectedId) rememberSessionSelection(selectionKey, selectedId);
  }, [connected, selectionKey, selectedId]);
  function selectSession(sessionId: string) {
    draftCreation.hide();
    dispatch({ type: "session.selected", sessionId });
  }
  const history = useSessionHistory(selectionKey ?? client, selectedId, state.remote.sessions, selectSession);
  const panelOpen = state.local.dockOpen;
  const environmentOpen = state.local.dockOpen && state.local.dockTab === "environment";
  const tasksOpen = state.local.dockOpen && state.local.dockTab === "tasks";
  const selected = !draft && selectedId ? state.remote.sessions[selectedId] : undefined;
  const visibleMessages = selected?.messages.filter((message) => message.systemNotice !== "resumesRuntime");
  const conversationOpen = Boolean(selected || draft);
  const firstMessage = selected && firstMessages[selected.id];
  const preview = firstMessage && firstMessage.continuityId === selected?.context.continuityId ? firstMessage : null;
  useEffect(() => {
    const completed = Object.entries(firstMessages).filter(([id, preview]) => {
      const session = state.remote.sessions[id];
      return session && session.context.continuityId === preview.continuityId
        && session.messages.some((message) => message.role === "user") && !waitingForFirstReply(session, preview);
    });
    if (completed.length) setFirstMessages((current) => {
      const remaining = { ...current };
      for (const [id, preview] of completed) if (current[id] === preview) delete remaining[id];
      return remaining;
    });
  }, [state.remote.sessions, firstMessages]);
  const operationScope = selected ? JSON.stringify([selectionKey, selected.id]) : null;
  const failure = operationScope ? operationFailures[operationScope] : undefined;
  function reportFailure(notice: Notice, pending?: { id: string; text: string; instanceId?: string }) {
    if (operationScope) setOperationFailures((current) => current[operationScope]?.pending && !pending
      ? current : { ...current, [operationScope]: { notice, pending } });
  }
  function clearFailure() {
    if (operationScope) setOperationFailures(({ [operationScope]: _, ...rest }) => rest);
  }
  async function checkConversation() {
    const pending = failure?.pending;
    if (selected && pending?.instanceId && client.findSubmission) {
      const result = await client.findSubmission(selected.id, pending.id, pending.instanceId).catch(() => null);
      if (result?.accepted && result.submissionId === pending.id) {
        dispatch({ type: "draft.submitted", sessionId: selected.id, expected: pending.text });
        clearFailure();
      }
    }
    refreshRef.current?.();
  }
  const [openGoalScope, setOpenGoalScope] = useState<string | null>(null);
  const goalPanelId = useId();
  const goalSource = state.remote.source.kind === "live" ? state.remote.source : null;
  const canReadGoalHistory = selected?.supportsInteractiveGoalRecovery && client.interactiveGoalRecovery;
  const canControlGoal = !selected?.supportsInteractiveGoalRecovery && selected?.supportsInteractiveGoal
    && client.createInteractiveGoal && client.interactiveGoalStatus;
  const goalPanelScope = selected && goalSource && (canReadGoalHistory || canControlGoal)
    ? JSON.stringify([goalSource.connectionId, goalSource.serviceInstanceId, goalSource.muxSpaceId, selected.id]) : null;
  const goalPanelOpen = tasksOpen && goalPanelScope !== null && goalPanelScope === openGoalScope;
  const rightVisible = Boolean(selected) && state.local.dockOpen;
  const openTasks = () => dispatch({ type: "dock.opened", tab: "tasks" });
  const toggleEnvironment = () => dispatch(environmentOpen ? { type: "dock.closed" } : { type: "dock.opened", tab: "environment" });
  const toggleDock = () => dispatch(panelOpen ? { type: "dock.closed" }
    : { type: "dock.opened", tab: state.local.dockTab });
  const rightWidth = 380;
  const remainingWidth = viewportWidth - (sidebarOpen && viewportWidth > 760 ? sidebarWidth : 48);
  const stackedRight = rightVisible && remainingWidth < rightWidth + 360;
  useEffect(() => {
    if (goalPanelOpen && stackedRight) document.getElementById(goalPanelId)?.scrollIntoView?.({ block: "nearest" });
  }, [goalPanelOpen, goalPanelId, stackedRight]);
  const run = selected?.run;
  const stepIndex = run ? run.tasks.findIndex((item) => item.id === run.currentTaskId) : -1;
  const runSummary = run && (stepIndex >= 0
    ? t("panels:progress.step", { current: stepIndex + 1, total: run.tasks.length })
    : t("panels:progress.complete", { completed: run.tasks.filter((item) => item.status === "completed").length, total: run.tasks.length }));
  const tasksAvailable = hasCapability(state, "tasks");
  const changesAvailable = hasCapability(state, "changes");
  const modelScope = connected && selected && selectedId && state.remote.source.kind === "live"
    ? JSON.stringify([selectionKey, state.remote.source.serviceInstanceId, state.remote.source.connectionEpoch, selectedId])
    : null;
  const modelQuery = JSON.stringify([modelScope, selected?.execution?.id, selected?.execution?.status]);
  const goalBusy = Boolean(modelScope && goalBusyScope === modelScope);
  const modelRunning = selected?.status === "running" || goalBusy;
  const confirmedModels = modelResult?.scope === modelScope && (modelRunning || modelResult.query === modelQuery)
    ? modelResult
    : null;
  const sessionModels = confirmedModels?.models ?? null;
  const modelLabel = !modelScope || !client.sessionModels || modelRunning ? "none"
    : !confirmedModels ? "loading"
    : !sessionModels ? "unavailable"
    : sessionModels.models.length === 0 ? "empty" : "choose";
  const canChangeModel = Boolean(client.selectModel && sessionModels && (
    sessionModels.models.some((model) => model.id !== sessionModels.currentId)
    || (sessionModels.thinking?.availableLevels.length ?? 0) > 1
  ));
  useEffect(() => {
    if (!modelScope || !selectedId || modelRunning || !client.sessionModels) return;
    let active = true;
    const request = ++modelRequest.current;
    setModelResult(null);
    void client.sessionModels(selectedId).then((models) => {
      if (active && request === modelRequest.current) setModelResult({ scope: modelScope, query: modelQuery, models });
    }).catch(() => {
      if (active && request === modelRequest.current) {
        setModelResult({ scope: modelScope, query: modelQuery, models: null });
        setNotice({ key: "notice.modelsUnavailable" });
      }
    });
    return () => { active = false; };
  }, [client, selectedId, modelScope, modelQuery, modelRunning]);
  const awaitingPublication = selectedId ? publications[selectedId] : undefined;
  useEffect(() => {
    if (!connected || state.remote.source.kind !== "live") return;
    const source = state.remote.source;
    const resolved = Object.entries(publications).filter(([id, receipt]) => {
      const session = state.remote.sessions[id];
      if (!session) return false;
      if (receipt.source.kind !== "live" || receipt.source.connectionId !== source.connectionId
        || receipt.source.serviceInstanceId !== source.serviceInstanceId) return true;
      const execution = session.execution?.id === receipt.executionId ? session.execution : null;
      const contentPublished = session.cursor !== receipt.cursor;
      const terminal = execution?.status === "succeeded" || execution?.status === "failed" || execution?.status === "interrupted";
      if (!contentPublished && !terminal) return false;
      if (receipt.draftText !== undefined && receipt.executionId && (contentPublished || execution?.status === "succeeded")) {
        dispatch({ type: "draft.submitted", sessionId: id, expected: receipt.draftText });
      }
      return true;
    });
    if (resolved.length) setPublications((current) => {
      const remaining = { ...current };
      for (const [id, receipt] of resolved) if (current[id] === receipt) delete remaining[id];
      return remaining;
    });
  }, [connected, publications, state.remote.source, state.remote.sessions]);
  const controlsAllowed = installedClient === client && selectionReady && !syncing && !controlPending && (
    (state.remote.source.kind === "fixture" && state.remote.connection === "fixture-offline")
    || (state.remote.source.kind === "live" && connected)
  );
  const goalStart = useGoalStart(client, selected, connected && state.remote.source.kind === "live"
    ? state.remote.source : null, controlsAllowed);
  const mutationsAllowed = controlsAllowed && !awaitingPublication && !modelPending;
  const submitAllowed = mutationsAllowed && !goalBusy && !failure?.pending && (
    state.remote.source.kind === "fixture"
    || sessionModels?.models.some((model) => model.id === sessionModels.currentId)
  );
  useLayoutEffect(() => {
    transcriptPosition.current = state.local.transcriptScrollTop;
  }, [state.local.transcriptScrollTop]);
  useLayoutEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript || typeof ResizeObserver === "undefined") return;
    const measure = () => {
      setTranscriptScrollbar(transcript.offsetWidth - transcript.clientWidth);
      if (transcriptPosition.current === null) transcript.scrollTop = transcript.scrollHeight;
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(transcript);
    return () => observer.disconnect();
  }, [conversationOpen]);
  useLayoutEffect(() => {
    const transcript = transcriptRef.current;
    if (transcript) transcript.scrollTop = transcriptPosition.current ?? transcript.scrollHeight;
  }, [selected]);
  const selectedDocument = selected
    ? findSelectedDocument(selected, state.local.selectedDocuments[selected.id] ?? null)
    : undefined;
  const quickLookDocument = selected?.documents.find(
    (document) => document.id === state.local.quickLookDocumentId,
  );

  const choiceKey = selected && state.remote.source.kind === "live"
    ? JSON.stringify([state.remote.source.serviceInstanceId, selected.id]) : null;
  const question = selected?.userChoice;
  const storedAnswer = choiceKey ? choiceAnswers[choiceKey] : undefined;
  const choiceAnswer = question && storedAnswer?.questionId === question.questionId ? storedAnswer : undefined;
  const rejectedBeforeInput = choiceAnswer?.executionId && selected?.execution?.id === choiceAnswer.executionId
    && (selected.execution.status === "failed" || selected.execution.status === "interrupted");

  function updateAnswer(answer: ChoiceAnswer) {
    if (choiceKey) setChoiceAnswers((current) => ({ ...current, [choiceKey]: answer }));
  }

  async function submit(text: string, answer?: ChoiceAnswer): Promise<void> {
    if (!selected || syncPendingRef.current || controlPendingRef.current || !submitAllowed || selected.status === "running") return;
    if (answer && (question?.questionId !== answer.questionId
      || ((choiceAnswer?.status === "unknown" || choiceAnswer?.status === "accepted") && !rejectedBeforeInput))) return;
    if (!text.trim()) {
      setNotice({ key: "notice.emptyPrompt" });
      return;
    }
    const submissionId = fixture
      ? `gui-fixture-submission-${submissionCounter.current++}`
      : `gui-${crypto.randomUUID()}`;
    const instanceId = state.remote.source.kind === "live" ? state.remote.source.serviceInstanceId : undefined;
    const pending = { id: submissionId, text, instanceId };
    controlPendingRef.current = true;
    setControlPending("submit");
    try {
      const receipt = await client.submitText({ sessionId: selected.id, submissionId, text });
      if (receipt.submissionId !== submissionId) throw new Error("Mismatched submission receipt");
      if (!receipt.accepted) {
        const unknown = receipt.reason === "submission_outcome_unknown";
        if (answer) updateAnswer({ ...answer, status: unknown ? "unknown" : "rejected", executionId: undefined });
        reportFailure(unknown ? { key: "notice.unknownSubmission" }
          : { key: "notice.rejected", params: { reason: receipt.reason ?? "" } }, unknown ? pending : undefined);
        return;
      }
      clearFailure();
      if (answer) updateAnswer({ ...answer, status: "accepted", executionId: receipt.executionId });
      else if (!receipt.executionId) dispatch({ type: "draft.submitted", sessionId: selected.id, expected: text });
      if (!fixture) setPublications((current) => ({
        ...current, [selected.id]: {
          source: state.remote.source, cursor: selected.cursor, executionId: receipt.executionId,
          draftText: answer ? undefined : text,
        },
      }));
      setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
      setNotice(fixture
        ? { key: "notice.fixtureAccepted" }
        : { key: "notice.liveAccepted" });
    } catch {
      if (answer) updateAnswer({ ...answer, status: "unknown", executionId: undefined });
      reportFailure({ key: "notice.submitFailed" }, pending);
    } finally {
      controlPendingRef.current = false;
      setControlPending(null);
    }
  }

  async function advance(): Promise<void> {
    if (!fixture || syncPendingRef.current || !mutationsAllowed) return;
    const step = await fixture.advanceFixture();
    if (!step) {
      setNotice({ key: "notice.noEvent" });
      return;
    }
    setRemainingSteps(step.remaining);
    setNotice({ key: "notice.playback", params: { label: step.label } });
  }

  async function interrupt(): Promise<void> {
    if (!selected || syncPendingRef.current || controlPendingRef.current || !controlsAllowed || selected.status !== "running") return;
    controlPendingRef.current = true;
    setControlPending("interrupt");
    try {
      const receipt = await client.interrupt(selected.id);
      setRemainingSteps(fixture?.remainingFixtureSteps() ?? 0);
      if (receipt.accepted) setNotice(fixture ? { key: "notice.fixtureInterrupted" } : { key: "notice.interruptRequested" });
      else reportFailure({ key: "notice.interruptReason", params: { reason: receipt.reason ?? "" } });
    } catch {
      reportFailure({ key: "notice.interruptFailed" });
    } finally {
      controlPendingRef.current = false;
      setControlPending(null);
    }
  }

  async function selectModel(modelId: string, level?: ThinkingLevel): Promise<SessionModels | null> {
    if (!selected || !modelScope || !client.selectModel || modelRunning || modelPending || awaitingPublication || controlPendingRef.current) return null;
    const request = ++modelRequest.current;
    setModelPending(true);
    try {
      const models = level === undefined
        ? await client.selectModel(selected.id, modelId)
        : await client.selectModel(selected.id, modelId, level);
      if (request !== modelRequest.current) return null;
      const choice = models.models.find((model) => model.id === models.currentId);
      if (!choice || choice.id !== modelId) throw new Error("Unconfirmed model selection");
      setModelResult({ scope: modelScope, query: modelQuery, models });
      if (!failure?.pending) clearFailure();
      setNotice(level === undefined ? { key: "notice.modelChanged", params: { model: choice.label } } : { key: "notice.thinkingChanged" });
      return models;
    } catch {
      if (request !== modelRequest.current) return null;
      if (level === undefined && sessionModels) {
        setModelResult({ scope: modelScope, query: modelQuery, models: { currentId: null, models: sessionModels.models } });
      }
      if (!failure?.pending) reportFailure({ key: level === undefined ? "notice.modelRejected" : "notice.thinkingRejected" });
      return null;
    } finally {
      setModelPending(false);
    }
  }

  function openReview(documentId: string): void {
    if (!selected) return;
    restoreQuickLookFocusRef.current = false;
    dispatch({ type: "document.selected", sessionId: selected.id, documentId });
    dispatch({ type: "dock.opened", tab: "review" });
    dispatch({ type: "quick-look.closed" });
  }

  function reviewDiff(path: string) {
    if (!changesAvailable || !selected) return;
    const file = selected.changeSet?.files.find((item) => item.path === path);
    if (!file || !selected.documents.some((document) => document.id === file.documentId && document.kind === "diff")) return;
    return () => openReview(file.documentId);
  }

  function closeQuickLook(): void {
    restoreQuickLookFocusRef.current = true;
    dispatch({ type: "quick-look.closed" });
  }

  const draftPending = isSendingDraft(draft);
  const showWelcome = draft?.status === "ready" || (selected?.status === "idle"
    && !visibleMessages?.length && !preview && !selected.execution && !selected.run && !selected.changeSet
    && !selected.pendingApprovals?.length && !question && !goalStart.start && !goalStart.attempt);
  const firstMessageText = draftPending ? draft.text
    : preview && selected && !selected.messages.some((message) => message.role === "user") ? preview.text : null;
  const firstMessageStatus = draftPending ? { key: `notice.${draft.status}` } as const
    : preview && selected && waitingForFirstReply(selected, preview) ? { key: "notice.waitingForReply" } as const : null;
  useLayoutEffect(() => {
    const transcript = transcriptRef.current;
    if (draftPending && transcript) transcript.scrollTop = transcript.scrollHeight;
  }, [draftPending]);
  const draftTitle = t("workspace:sidebar.newSession");
  const workspaceContext = draft && projectNavigation ? draft.target.workspace
    : selected && installedClient === client && selectionReady ? requestedSelection?.workspace : undefined;
  const workspaceFingerprint = selected?.context.scopeFingerprint;
  const workspaceSessionId = selected?.context.sessionId;
  const temporaryWorkspace = workspaceContext === TEMPORARY_WORKSPACE;
  const readPreview = client.previewWorkspace;
  const previewSource = state.remote.source.kind === "live" ? state.remote.source : null;
  const serviceInstanceId = previewSource?.serviceInstanceId;
  const connectionEpoch = previewSource?.connectionEpoch;
  const scopeSessionId = selected?.id;
  const workspaceScope = useMemo(() => connected && selectionReady && serviceInstanceId && connectionEpoch && scopeSessionId && workspaceFingerprint
    ? { sessionId: scopeSessionId, serviceInstanceId, connectionEpoch }
    : null, [connected, selectionReady, serviceInstanceId, connectionEpoch, scopeSessionId, workspaceFingerprint]);
  const previewScope = readPreview ? workspaceScope : null;
  const workspaceScopeKey = workspaceScope ? JSON.stringify([previewSource?.connectionId, workspaceFingerprint, workspaceScope]) : null;
  const previewScopeKey = previewScope ? workspaceScopeKey : null;
  const [workspaceLocation, setWorkspaceLocation] = useState<{ key: string; path: string }>();
  useEffect(() => {
    if (!temporaryWorkspace || !workspaceScope || !workspaceScopeKey || !client.locateWorkspace) return;
    let active = true;
    void client.locateWorkspace(workspaceScope).then((path) => {
      if (active) setWorkspaceLocation({ key: workspaceScopeKey, path });
    }).catch(() => {});
    return () => { active = false; };
  }, [client, temporaryWorkspace, workspaceScope, workspaceScopeKey]);
  const workspacePath = temporaryWorkspace
    ? workspaceLocation?.key === workspaceScopeKey ? workspaceLocation?.path : undefined
    : workspaceContext ?? undefined;
  const inspectWorkspace = connected && !temporaryWorkspace && workspacePath && workspaceFingerprint && projectNavigation?.inspectWorkspace
    ? (review: boolean) => projectNavigation.inspectWorkspace!(
      workspacePath, workspaceFingerprint, review ? workspaceSessionId : undefined,
    ) : undefined;
  const openProjectPath = projectNavigation?.openProjectPath;
  const openWorkspacePath = useMemo(() => workspaceScope && workspaceContext && workspaceFingerprint && openProjectPath
    ? (file?: string) => openProjectPath(workspaceContext, workspaceFingerprint, file)
    : undefined, [workspaceScope, workspaceContext, workspaceFingerprint, openProjectPath]);
  const [filePreview, setFilePreview] = useState<{
    scope: string; reference: FileReference; trigger: HTMLButtonElement;
  }>();
  useEffect(() => {
    setFilePreview((current) => current?.scope === previewScopeKey ? current : undefined);
  }, [previewScopeKey]);
  const openFilePreview = useMemo(() => previewScopeKey ? (reference: FileReference, trigger: HTMLButtonElement) => {
    setFilePreview({ scope: previewScopeKey, reference, trigger });
  } : undefined, [previewScopeKey]);
  const replyCopies = copyableReplies(visibleMessages ?? [], selected?.status === "running"
    || Boolean(question && choiceAnswer?.status !== "accepted") || Boolean(selected?.pendingApprovals?.length));
  const projectContext = workspaceContext && workspaceContext !== TEMPORARY_WORKSPACE
    ? workspaceName(workspaceContext) : undefined;
  const conversationTitle = selected ? displaySessionTitle(selected, liveTitles[selected.id])
    : draftPending ? firstPromptTitle(draft.text)
      : projectContext ? `${projectContext} / ${draftTitle}` : draftTitle;
  const newSessionEnabled = !draftPending && (projectNavigation
    ? projectNavigation.available && !projectNavigation.pending
    : Boolean(client.createSession) && connected);

  function openDraft(path: string | null) {
    if (!newSessionEnabled) return;
    const sourceSessionId = state.local.selectedSessionId ?? undefined;
    const loadModels = projectNavigation?.draftModels;
    draftCreation.open({
      key: JSON.stringify([draftHost, path]),
      hostKey: draftHost,
      workspace: path,
      loadModels: loadModels ? () => loadModels(path) : undefined,
      create: async (continuityId) => {
        if (projectNavigation) return projectNavigation.createChat(path, continuityId, draftTitle);
        let sessionId: string | undefined;
        try {
          const receipt = await client.createSession!({ sourceSessionId, title: draftTitle, continuityId });
          if ("rejected" in receipt) return null;
          sessionId = receipt.sessionId;
        } catch {
          // Reconcile only by the exact Continuity ID in this launched Mux.
        }
        return { client, sessionId, show: () => true, refresh: client.requestResync };
      },
    });
    setDraftFocus((focus) => focus + 1);
  }

  const sidebarDrafts: SidebarDraft[] = draftCreation.drafts.filter((item) => item.target.hostKey === draftHost)
    .map((item) => ({
      id: item.id, workspace: item.target.workspace, sessionId: item.binding?.sessionId,
      title: isSendingDraft(item) ? firstPromptTitle(item.text) : draftTitle, selected: draftId === item.id, onSelect: () => openDraft(item.target.workspace),
    }));
  // The connected Session can arrive before the background directory refresh.
  if (projectNavigation && workspaceContext && selected?.context.continuityId?.startsWith("gui-draft-")) {
    const directory = projectNavigation.directory;
    const chats = workspaceContext === TEMPORARY_WORKSPACE ? directory.temporarySessions
      : directory.projects.find((project) => project.path === workspaceContext)?.sessions;
    if (!chats?.some((chat) => chat.id === selected.id)) sidebarDrafts.unshift({
      id: selected.id, workspace: workspaceContext === TEMPORARY_WORKSPACE ? null : workspaceContext,
      title: conversationTitle, selected: true, onSelect: () => selectSession(selected.id),
    });
  }

  const navigation: ProjectNavigationProps | undefined = projectNavigation ? {
    ...projectNavigation,
    selection: draft ? null : projectNavigation.selection,
    pending: projectNavigation.pending || draftPending,
    create: openDraft,
    select: (workspace, id) => {
      draftCreation.hide();
      projectNavigation.select(workspace, id);
    },
  } : undefined;
  const draftEnabled = projectNavigation ? projectNavigation.available && !projectNavigation.pending
    : connected || Boolean(draft?.binding);
  const draftModelTarget = draftCreation.draft?.target;
  const draftModels = useDraftModels(
    draftModelTarget?.hostKey === draftHost ? draftModelTarget : undefined, draftEnabled, draftCreation.draft?.modelId,
  );
  async function selectDraftModel(id: string) {
    if (!draftModels.models?.models.some((model) => model.id === id)) return null;
    draftCreation.selectModel(id);
    return { ...draftModels.models, currentId: id };
  }
  const draftModelId = draftModels.models?.currentId ?? undefined;
  const canSendDraft = draftEnabled && !draftPending && canSubmitDraft(draft)
    && (!draftModels.required || Boolean(draftModelId));
  function submitDraft() {
    if (canSendDraft) void draftCreation.submit(draftModelId);
  }

  const composer = draft ? {
    text: draftPending ? "" : draft.text,
    onChange: draftCreation.change,
    onSubmit: submitDraft,
    submitLabel: draft.status === "createUnknown" ? t("session:composer.checkCreation") : undefined,
    disabled: draftPending || draft.status === "firstSubmissionUnknown",
    buttonDisabled: !canSendDraft,
  } : selected ? {
    text: state.local.drafts[selected.id] ?? "",
    onChange: (value: string) => dispatch({ type: "draft.changed", sessionId: selected.id, value }),
    onSubmit: () => void submit(state.local.drafts[selected.id] ?? ""),
    disabled: installedClient !== client || !selectionReady,
    onInterrupt: selected.status === "running" ? () => void interrupt() : undefined,
    buttonDisabled: selected.status === "running" ? !controlsAllowed : !submitAllowed || !(state.local.drafts[selected.id] ?? "").trim(),
    notice: <p className="visually-hidden" role="status"><NoticeText notice={notice} /></p>,
  } : null;

  return (
    <ContextMenuProvider><div className={`desktop-shell ${native ? "native-shell" : "web-shell"}`}
      onPointerDownCapture={(event) => { event.currentTarget.dataset.inputModality = "pointer"; }}
      onKeyDownCapture={(event) => { event.currentTarget.dataset.inputModality = "keyboard"; }}>
      <DesktopFrame sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen((open) => !open)}
        {...history}
        onSettings={openSettings}
        onNewSession={newSessionEnabled ? () => openDraft(null) : undefined}
        onOpenFolder={projectNavigation?.available && !projectNavigation.pending ? projectNavigation.openFolder : undefined}
        onFocusComposer={selected || draft ? () => document.getElementById("message-input")?.focus() : undefined}
        environmentOpen={environmentOpen}
        onToggleEnvironment={selected ? toggleEnvironment : undefined}
        dockOpen={panelOpen}
        onToggleDock={selected ? toggleDock : undefined} />
      <main style={{ "--rail-width": `${sidebarOpen ? sidebarWidth : 48}px`, "--right-width": `${rightWidth}px` } as React.CSSProperties} className={`app-shell desktop-layout${sidebarOpen ? "" : " sidebar-closed"}${rightVisible ? " right-visible" : " dock-closed"}${stackedRight ? " right-stacked" : ""}`}>
        {!sidebarOpen ? <aside className="collapsed-rail" aria-label={shellText("collapsedSidebar")}>
          <button className="frame-icon" aria-label={shellText("toggleSidebar")} title={shellText("toggleSidebarHint")} aria-expanded="false" onClick={() => setSidebarOpen(true)}><PanelIcon side="left" /></button>
          <AccountMenu compact account={account} onSettings={openSettings} />
        </aside> : null}
        <div className="sidebar-container" hidden={!sidebarOpen}>
        <Sidebar
          onToggleSidebar={() => setSidebarOpen(false)}
          onSettings={openSettings}
          state={state}
          account={account}
          managedLocal={Boolean(hostSettings)}
          onSelect={selectSession}
          onToggleWorkspace={(workspaceId) => dispatch({ type: "workspace.toggled", workspaceId })}
          onNewSession={() => openDraft(null)}
          newSessionEnabled={newSessionEnabled}
          activeSessionId={selected?.id ?? null}
          drafts={sidebarDrafts}
          projectNavigation={navigation}
          projectTitles={{ ...knownTitles, ...liveTitles }}
        />
        <div className="sidebar-resizer" role="separator" aria-label={t("panels:layout.sidebarWidth")} aria-orientation="vertical" tabIndex={0}
          aria-valuemin={200} aria-valuemax={420} aria-valuenow={sidebarWidth}
          onDoubleClick={() => setSidebarWidth(280)}
          onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); setSidebarWidth((width) => Math.max(200, Math.min(420, width + (event.key === "ArrowLeft" ? -10 : 10)))); } }}
          onPointerDown={(event) => { if (event.button !== 0) return; sidebarDrag.current = { x: event.clientX, width: sidebarWidth }; event.currentTarget.setPointerCapture(event.pointerId); }}
          onPointerMove={(event) => { const drag = sidebarDrag.current; if (drag) setSidebarWidth(Math.max(200, Math.min(420, drag.width + event.clientX - drag.x))); }}
          onPointerUp={() => { sidebarDrag.current = null; }} onPointerCancel={() => { sidebarDrag.current = null; }} onLostPointerCapture={() => { sidebarDrag.current = null; }} />
        </div>

        {conversationOpen || (attachedClient && !fixture) ? <SessionHeader
          title={conversationOpen ? conversationTitle : undefined}
          contextLabel={workspaceContext === TEMPORARY_WORKSPACE ? t("workspace:sidebar.temporaryChats")
            : selected ? projectContext : undefined}
          sessionReady={Boolean(selected)}
          connection={displayedConnection}
          dockOpen={panelOpen}
          onOpenDock={toggleDock}
        /> : null}

        <section style={{ "--scrollbar-width": `${transcriptScrollbar}px` } as React.CSSProperties} className="conversation-pane" aria-label={t("panels:layout.workspace")}>
          {startLocalHost ? <div className="diagnostic">{startLocalHost}</div> : null}
          {attachedClient && !liveConnecting && (syncing || state.diagnostic || state.remote.connection === "disconnected") ? (
            <div className="diagnostic" role="status">
              <span>{syncing ? t("session:sync.fixture") : t("session:diagnostic.title")}</span>
              {state.diagnostic ? <details><summary>{t("session:diagnostic.details")}</summary><pre>{state.diagnostic}</pre></details> : null}
              {fixture ? <button type="button" disabled={syncing} onClick={() => refreshRef.current?.()}>{t("session:sync.retry")}</button> : null}
            </div>
          ) : null}
          {composer ? (
            <>
              <div className="transcript markdown-reading"
                data-markdown-theme={markdown.theme}
                aria-label={t("session:transcript.label")} aria-live="polite" ref={transcriptRef}
                onScroll={selected ? (event) => {
                  const { scrollTop, scrollHeight, clientHeight } = event.currentTarget;
                  const following = !fixture && scrollHeight - clientHeight - scrollTop <= 32;
                  dispatch({ type: "transcript.scrolled", sessionId: selected.id, scrollTop: following ? null : scrollTop });
                } : undefined}>
                <div className="transcript-content">
                  {showWelcome ? <h2 className="chat-welcome">{t("session:welcome")}</h2> : null}
                  {firstMessageText !== null ? <article className="message user" aria-label={t("session:transcript.message", { role: valueLabel("user") })}>
                    <p>{firstMessageText}</p>
                  </article> : null}
                  {selected ? <Fragment key={selected.id}>
                    {visibleMessages?.map((message) => {
                      const choice = message.role === "user" ? submittedChoiceLabel(message.content) : undefined;
                      if (choice) return <ChoiceReceipt key={message.id} label={choice} text={message.content} />;
                      return message.role === "status" ? (
                      <p className="message transcript-status" role="status" key={message.id}>{message.content}</p>
                    ) : (
                      <article className={`message ${message.role}`} key={message.id} aria-label={t("session:transcript.message", { role: valueLabel(message.role) })}>
                        <div className="message-meta">
                          <strong>{message.role === "user" ? t("session:transcript.you") : t("session:transcript.harness")}</strong>
                          <span>{valueLabel(message.phase)}</span>
                        </div>
                        {message.role === "assistant" && message.content
                          ? <MessageMarkdown text={message.content} openFile={openWorkspacePath ? undefined : openFilePreview}
                            revealFile={openWorkspacePath} />
                          : <p>{message.content || t(message.phase === "streaming" ? "session:transcript.waiting" : "session:transcript.noText")}</p>}
                        {replyCopies.has(message.id)
                          ? <div className="reply-actions"><CopyButton text={replyCopies.get(message.id)!}
                              icon feedbackMs={1600} label={t("session:transcript.copyReply")} /></div>
                          : null}
                      </article>
                    ); })}
                    {selected.pendingApprovals?.map((approval) => (
                      <ToolApproval key={approval.interactionId} approval={approval}
                        scope={projectContext ?? (workspaceContext === TEMPORARY_WORKSPACE ? t("workspace:sidebar.temporaryChats") : undefined)}
                        enabled={connected && selectionReady && !syncing && Boolean(client.respondInteraction)}
                        onRespond={(outcome) => {
                          if (approval.sessionId === selected.id) {
                            void client.respondInteraction?.(selected.id, approval.interactionId, outcome);
                          }
                        }} />
                    ))}
                    {question && choiceKey ? <UserChoiceCard key={question.questionId} question={question}
                      answer={rejectedBeforeInput && choiceAnswer ? { ...choiceAnswer, status: "rejected" } : choiceAnswer}
                      enabled={Boolean(submitAllowed && selected.status !== "running")}
                      onChange={updateAnswer} onConfirm={(text, answer) => void submit(text, answer)} /> : null}
                    {selected.execution || (tasksAvailable && selected.run) || goalStart.start || goalStart.attempt ? <button
                      className="execution-summary" type="button" onClick={openTasks}>
                      {selected.execution ? t(!fixture && !connected ? "panels:execution.lastKnownStatus" : "panels:execution.status",
                        { status: valueLabel(selected.execution.status) })
                        : runSummary ?? t("panels:dock.tasks")}
                      <span aria-hidden="true">›</span>
                    </button> : null}
                    {selected.changeSet && changesAvailable ? (
                      <ChangeSetCard
                        changeSet={selected.changeSet}
                        onOpenFile={(documentId, trigger) => {
                          quickLookTriggerRef.current = trigger;
                          dispatch({ type: "quick-look.opened", documentId });
                        }}
                        onOpenReview={() => {
                          const first = selected.changeSet?.files[0];
                          if (first) openReview(first.documentId);
                        }}
                      />
                    ) : null}
                  </Fragment> : null}
                  {firstMessageStatus ? <p className="message first-turn-status" role="status">
                    <span className="first-turn-spinner" aria-hidden="true" />
                    <NoticeText notice={firstMessageStatus} />
                  </p> : null}
                  {draft && draft.status !== "ready" && !draftPending ? <div
                    className={draft.unconfirmed ? "operation-notice uncertain" : "operation-notice"}
                    role={draft.unconfirmed || draft.status === "createUnknown" ? "status" : "alert"}>
                    <NoticeText notice={{ key: `notice.${draft.status}` }} />
                    {draft.unconfirmed ? <button type="button" className="secondary-button"
                      onClick={() => void draftCreation.check()}>{t("session:composer.checkConversation")}</button> : null}
                  </div> : null}
                </div>
              </div>

              {filePreview && filePreview.scope === previewScopeKey && previewScope && readPreview
                ? <WorkspacePreviewDialog key={previewScopeKey} initial={filePreview.reference} theme={markdown.theme}
                  read={(reference, base) => readPreview({ ...previewScope, reference, base })}
                  onClose={() => {
                    setFilePreview(undefined);
                    filePreview.trigger.focus({ preventScroll: true });
                  }} />
                : null}

              {quickLookDocument && changesAvailable ? (
                <QuickLook
                  document={quickLookDocument}
                  onClose={closeQuickLook}
                  onOpenReview={() => openReview(quickLookDocument.id)}
                />
              ) : null}

              {selected && fixture ? <details className="playback-strip" aria-label={t("session:fixture.controls")}>
                <summary>{t("session:fixture.summary", { count: remainingSteps })}</summary>
                <div className="playback-body">
                <div>
                  <strong>{t("session:fixture.deterministic")}</strong>
                  <span>{t("session:fixture.queued", { count: remainingSteps })}</span>
                  <small>{t(bridgeLabels[bridgeProbe.status])}</small>
                </div>
                <button type="button" disabled={!mutationsAllowed} onClick={() => void advance()}>{t("session:fixture.advance")}</button>
                </div>
              </details> : null}

              <div className="composer-stack">
                {selected && failure ? <div className={failure.pending ? "operation-notice uncertain" : "operation-notice"} role={failure.pending ? "status" : "alert"}>
                  <span><NoticeText notice={failure.notice} /></span>
                  {failure.pending ? <button type="button" className="secondary-button"
                    onClick={() => void checkConversation()}>{t("session:composer.checkConversation")}</button> : null}
                  {!failure.pending ? <button type="button" className="secondary-button"
                    onClick={clearFailure}>{t("session:composer.dismissNotice")}</button> : null}
                </div> : null}
                <MessageComposer {...composer} title={conversationTitle} fixture={Boolean(fixture)}
                  leadingAction={goalPanelScope ? <button type="button" className="composer-goal"
                    aria-label={t("panels:interactiveGoal.title")} title={t("panels:interactiveGoal.title")}
                    aria-expanded={goalPanelOpen} aria-controls={goalPanelId} onClick={() => {
                      setOpenGoalScope(goalPanelOpen ? null : goalPanelScope);
                      if (!goalPanelOpen) openTasks();
                    }}>{t("panels:interactiveGoal.shortcut")}</button> : null}
                  model={<ModelPicker
                    models={draft ? draftModels.models : sessionModels}
                    emptyLabel={draft ? draftModels.label : modelLabel}
                    disabled={draft
                      ? draftPending || draft.status === "firstSubmissionUnknown"
                        || !draftModels.models?.models.some((model) => model.id !== draftModelId)
                      : !canChangeModel || modelRunning || Boolean(awaitingPublication) || Boolean(controlPending)}
                    busy={Boolean(selected) && modelPending}
                    onSelect={draft ? selectDraftModel : selectModel}
                  />}
                />
              </div>
            </>
          ) : !liveConnecting ? (
            <div className="empty-state">
              <p>{t(attachedClient || projectNavigation?.available ? "session:emptySession" : "session:sync.offlineHost")}</p>
              {attachedClient ? <p role="status"><NoticeText notice={notice} /></p> : null}
            </div>
          ) : null}
        </section>

        {selected ? (
          <WorkDock key={JSON.stringify([selectionKey, selected.id])}
            open={rightVisible} stale={!fixture && !connected} tab={state.local.dockTab}
            state={state} session={selected} workspacePath={workspacePath} temporaryWorkspace={temporaryWorkspace} selectedDocument={selectedDocument}
            inspectWorkspace={inspectWorkspace} openWorkspacePath={openWorkspacePath}
            goalControls={<>
              <GoalStart {...goalStart} />
              {goalPanelScope && goalSource ? <div id={goalPanelId} hidden={!goalPanelOpen}>
                {canReadGoalHistory && goalPanelOpen ? <InteractiveGoalRecovery
                  key={JSON.stringify([goalPanelScope, goalSource.connectionEpoch])}
                  client={client} sessionId={selected.id} instanceId={goalSource.serviceInstanceId}
                  epoch={connected && selectionReady && !syncing ? goalSource.connectionEpoch : null} /> : null}
                {canControlGoal ? <InteractiveGoal key={goalPanelScope}
                  client={client} session={selected} instanceId={goalSource.serviceInstanceId}
                  epoch={connected && selectionReady && !syncing ? goalSource.connectionEpoch : null}
                  enabled={goalPanelOpen && mutationsAllowed} reviewDiff={reviewDiff} scopeKey={modelScope} setBusyScope={setGoalBusyScope} /> : null}
              </div> : null}
            </>}
            goalProgress={selected.execution && selected.supportsGoalProgress && client.goalProgress && goalSource ? (
              <GoalProgress key={JSON.stringify([goalSource.serviceInstanceId, goalSource.muxSpaceId, selected.id, selected.execution.id])}
                client={client} sessionId={selected.id} execution={selected.execution} connected={connected} />
            ) : null}
            onClose={() => dispatch({ type: "dock.closed" })}
            onTab={(tab) => dispatch({ type: "dock.opened", tab })}
            onSelectDocument={(documentId) => dispatch({ type: "document.selected", sessionId: selected.id, documentId })}
            onToggleActivity={(id) => dispatch({ type: "activity.toggled", activityGroupId: id })}
            onSelectTask={(taskId) => dispatch({ type: "task.selected", taskId })}
            onSelectAgent={(agentRunId) => dispatch({ type: "agent.selected", agentRunId })}
          />
        ) : null}
      </main>
      <SettingsDialog dialogRef={settingsDialog} hostSettings={hostSettings} hostRequest={hostSettingsRequest}
        markdown={markdown} onMarkdownChange={setMarkdown} />
    </div></ContextMenuProvider>
  );
}

interface SidebarProps {
  readonly onToggleSidebar: () => void;
  readonly onSettings: () => void;
  readonly state: GuiState;
  readonly account?: OfflineAccount | null;
  readonly managedLocal: boolean;
  readonly onSelect: (sessionId: string) => void;
  readonly onToggleWorkspace: (workspaceId: string) => void;
  readonly onNewSession: () => void;
  readonly newSessionEnabled: boolean;
  readonly drafts: readonly SidebarDraft[];
  readonly activeSessionId: string | null;
  readonly projectNavigation?: ProjectNavigationProps;
  readonly projectTitles: Readonly<Record<string, string>>;
}

function Sidebar({ state, account, managedLocal, onSelect, onToggleWorkspace, onNewSession, newSessionEnabled, drafts, onToggleSidebar, onSettings, activeSessionId, projectNavigation, projectTitles }: SidebarProps) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const { t: shellText } = useTranslation("shell");
  const preferencesKey = sidebarPreferencesKey(state.remote.source);
  return (
    <aside className="session-rail" aria-label={t("workspace:sidebar.navigation")}>
      <div className="brand-row">
        {/* i18next-instrument-ignore-next-line: product name */}
        <strong className="brand-name">{appName}</strong>
        <div className="brand-actions">
          <button className="brand-search" type="button" aria-label={t("workspace:sidebar.searchUnavailable")} title={t("workspace:sidebar.searchHint")} disabled><UiIcon name="search" /></button>
          <button className="frame-icon" type="button" aria-label={shellText("toggleSidebar")} title={shellText("toggleSidebarHint")} aria-expanded="true" onClick={onToggleSidebar}><PanelIcon side="left" /></button>
        </div>
      </div>
      <div className="workspace-scroll">
      <nav className="sidebar-shortcuts" aria-label={t("workspace:sidebar.shortcuts")}>
        <button className="new-session" type="button" onClick={onNewSession}
          disabled={!newSessionEnabled}>
          <UiIcon name="new-session" />
          <span>{t("workspace:sidebar.newSession")}</span>
          <UiIcon name="plus" />
        </button>
        <button type="button" disabled title={t("workspace:sidebar.prHint")}><UiIcon name="pull-request" /><span>{t("workspace:sidebar.pullRequests")}</span></button>
        <button type="button" disabled title={t("workspace:sidebar.scheduleHint")}><UiIcon name="scheduled" /><span>{t("workspace:sidebar.scheduled")}</span></button>
        <button type="button" disabled title={t("workspace:sidebar.pluginsHint")}><UiIcon name="plugins" /><span>{t("workspace:sidebar.plugins")}</span></button>
      </nav>
      {!managedLocal ? <div className="fixture-banner"><span className="fixture-dot" />{state.remote.source.kind === "fixture" ? t("workspace:sidebar.fixtureBanner") : t("workspace:sidebar.liveBanner")}</div> : null}

      {projectNavigation
        ? <ProjectNavigation navigation={projectNavigation} selectedId={activeSessionId} titles={projectTitles} drafts={drafts} />
        : <SessionNavigation key={preferencesKey} preferencesKey={preferencesKey} state={state} activeSessionId={activeSessionId} drafts={drafts}
            projectTitles={projectTitles} onSelect={onSelect} onToggleWorkspace={onToggleWorkspace} />}

      </div>
      <AccountMenu account={account} onSettings={onSettings} />
    </aside>
  );
}

function SessionNavigation({ state, preferencesKey, onSelect, onToggleWorkspace, activeSessionId, drafts, projectTitles }: Pick<SidebarProps,
  "state" | "onSelect" | "onToggleWorkspace" | "activeSessionId" | "drafts" | "projectTitles"> & { readonly preferencesKey: string }) {
  const { t } = useTranslation("workspace");
  const [preferences, setPreferences] = useState(() => readSidebarPreferences(preferencesKey));
  const list = useRef<HTMLElement>(null);
  const restorePinFocus = useRef<string | null>(null);
  const { selectedSessionId } = state.local;
  const { sessions, sessionOrder, recentSessionIds, workspaces, workspaceOrder } = state.remote;
  const stale = isStale(state);

  useEffect(() => {
    if (!selectedSessionId || stale) return;
    setPreferences((current) => current.recent[0] === selectedSessionId ? current : {
      ...current,
      recent: [selectedSessionId, ...current.recent.filter((id) => id !== selectedSessionId)].slice(0, 128),
    });
  }, [selectedSessionId, stale]);

  useEffect(() => {
    if (preferencesKey === "fixture") { saveSidebarPreferences(preferencesKey, preferences); return; }
  }, [preferencesKey, preferences]);

  useEffect(() => {
    if (preferencesKey === "fixture") return;
    let active = true;
    let pending = false;
    const refresh = async () => {
      if (pending) return;
      pending = true;
      try {
        const value = await updateSidebarPreferences(preferencesKey);
        if (active) setPreferences(value);
      } catch { /* Keep the last confirmed records while disconnected. */ }
      finally { pending = false; }
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 1000);
    return () => { active = false; window.clearInterval(timer); };
  }, [preferencesKey]);

  useLayoutEffect(() => {
    const id = restorePinFocus.current;
    if (!id) return;
    restorePinFocus.current = null;
    Array.from(list.current?.querySelectorAll<HTMLButtonElement>("[data-pin-session]") ?? [])
      .find((button) => button.dataset.pinSession === id)?.focus();
  }, [preferences.pinned]);

  const knownSessions = new Set(sessionOrder.filter((id) => !drafts.some((draft) => draft.sessionId === id)));
  const pinned = new Set(preferences.pinned);
  const orderedIds = state.remote.source.kind === "live" ? [...sessionOrder].reverse()
    : [...new Set([...preferences.recent, ...recentSessionIds, ...sessionOrder])];
  const availableWorkspaces = hasCapability(state, "workspace") ? workspaceOrder : [];
  const workspaceIds = new Set(availableWorkspaces);
  const ungrouped: SessionSnapshot[] = [];
  const grouped = new Map<string, SessionSnapshot[]>();
  for (const id of orderedIds) {
    if (!knownSessions.has(id) || pinned.has(id)) continue;
    const session = sessions[id];
    if (!workspaceIds.has(session.workspaceId)) {
      ungrouped.push(session);
      continue;
    }
    const group = grouped.get(session.workspaceId) ?? [];
    group.push(session);
    grouped.set(session.workspaceId, group);
  }

  function renderSession(session: SessionSnapshot, isPinned = false) {
    return <SessionButton key={session.id} session={session} title={displaySessionTitle(session, projectTitles[session.id])} stale={stale}
      selected={session.id === activeSessionId} unread={Boolean(state.local.unread[session.id])}
      pinned={isPinned} onSelect={() => onSelect(session.id)} onTogglePin={() => {
        restorePinFocus.current = session.id;
        if (isPinned && workspaceIds.has(session.workspaceId) && state.local.expandedWorkspaces[session.workspaceId] === false) {
          onToggleWorkspace(session.workspaceId);
        }
        if (preferencesKey !== "fixture") {
          void updateSidebarPreferences(preferencesKey, isPinned ? "unpin" : "pin", session.id)
            .then(setPreferences).catch(() => {});
        } else {
          setPreferences((current) => ({ ...current,
            pinned: isPinned ? current.pinned.filter((id) => id !== session.id) : [session.id, ...current.pinned] }));
        }
      }} />;
  }

  const pinnedSessions = preferences.pinned.filter((id) => knownSessions.has(id)).map((id) => sessions[id]);
  return <nav ref={list} aria-label={t("sidebar.chats")}>
    {pinnedSessions.length ? <section className="sidebar-session-section" aria-labelledby="pinned-sessions">
      <h2 id="pinned-sessions" className="section-label">{t("sidebar.pinned")}</h2>
      {pinnedSessions.map((session) => renderSession(session, true))}
    </section> : null}
    <section className="sidebar-session-section" aria-labelledby="chat-sessions">
      <h2 id="chat-sessions" className="section-label">{t("sidebar.chats")}</h2>
      {drafts.map((draft) => <DraftChatRow key={draft.id} draft={draft} />)}
      {ungrouped.length ? <div className="workspace-group">
        {grouped.size ? <p className="section-label">{t("sidebar.unassigned")}</p> : null}
        {ungrouped.map((session) => renderSession(session))}
      </div> : null}
      {availableWorkspaces.map((id) => {
        const workspace = workspaces[id];
        const group = grouped.get(id);
        if (!group) return null;
        const expanded = state.local.expandedWorkspaces[id] ?? true;
        return <section className="workspace-group" key={id}>
          <button className="workspace-heading" type="button" aria-expanded={expanded}
            onClick={() => onToggleWorkspace(id)}>
            <span className="folder-glyph"><UiIcon name="folder" /></span>
            <span>{workspace.title}</span>
            <VcsBadge workspace={workspace} />
            <UiIcon name={expanded ? "chevron-up" : "chevron-down"} />
          </button>
          {expanded ? <div className="session-list">{group.map((session) => renderSession(session))}</div> : null}
        </section>;
      })}
    </section>
  </nav>;
}

function VcsBadge({ workspace }: { readonly workspace: WorkspaceSummary }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  if (!workspace.vcs) return <span className="vcs-badge none">{t("workspace:sidebar.plain")}</span>;
  return <span className={`vcs-badge ${workspace.vcs.kind}`}>{workspace.vcs.kind} · {workspace.vcs.label}</span>;
}

function SessionButton({ session, title, selected, unread, stale, pinned, onSelect, onTogglePin }: {
  readonly session: SessionSnapshot;
  readonly title: string;
  readonly selected: boolean;
  readonly unread: boolean;
  readonly stale: boolean;
  readonly pinned: boolean;
  readonly onSelect: () => void;
  readonly onTogglePin: () => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const openMenu = useContextMenu();
  const label = stale ? t("workspace:sidebar.stale", { status: valueLabel(session.status) }) : valueLabel(session.status);
  const pinLabel = t(pinned ? "workspace:sidebar.unpinChat" : "workspace:sidebar.pinChat", { title });
  return (
    <div className={`session-row${selected ? " selected" : ""}`}>
      <button
        className="session-item"
        type="button"
        aria-current={selected ? "page" : undefined}
        aria-label={t("workspace:sidebar.sessionLabel", { title, status: label })}
        onClick={onSelect} onContextMenu={(event) => openMenu(event, [{
          label: t(pinned ? "workspace:sidebar.unpin" : "workspace:sidebar.pin"), run: onTogglePin,
        }])}
      >
        <span className="session-title">{title}</span>
        <StatusMark status={session.status} stale={stale} />
        {unread ? <span className="unread-dot" aria-label={t("workspace:sidebar.unread")} /> : null}
      </button>
      <button type="button" className="session-pin" data-pin-session={session.id}
        data-pinned={pinned} aria-label={pinLabel} title={pinLabel} onClick={onTogglePin}>
        <UiIcon name="pin" />
      </button>
    </div>
  );
}

function StatusMark({ status, stale = false }: {
  readonly status: SessionSnapshot["status"];
  readonly stale?: boolean;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const label = stale ? t("workspace:sidebar.stale", { status: valueLabel(status) }) : valueLabel(status);
  return (
    <span className={`status-mark ${status}${stale ? " stale" : ""}`} title={label}>
      <span className="status-glyph" aria-hidden="true">{stale ? "–" : status === "running" ? "◌" : status === "waiting" ? "!" : status === "failed" ? "×" : ""}</span>
      <span className="sr-only">{label}</span>
    </span>
  );
}

function isStale(state: GuiState): boolean {
  return state.remote.connection === "disconnected" || state.remote.connection === "resync-required";
}

function ExecutionDetail({ execution, stale }: {
  readonly execution: NonNullable<SessionSnapshot["execution"]>;
  readonly stale: boolean;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <details className="execution-detail" aria-label={t("panels:execution.details")}>
      <summary>
        <span className={`run-indicator ${stale ? "unknown" : execution.status}`} aria-hidden="true">◌</span>
        <strong>{t("panels:execution.details")}</strong>
        <span className="execution-disclosure" aria-hidden="true">⌄</span>
      </summary>
      <dl>
        <dt>{t("panels:execution.title")}</dt><dd><code>{execution.id}</code></dd>
        <dt>{t("panels:execution.revision")}</dt><dd>{execution.revision}</dd>
        {execution.errorCode ? <><dt>{t("panels:execution.failureCode")}</dt><dd><code>{execution.errorCode}</code></dd></> : null}
        <dt>{t("panels:execution.source")}</dt><dd>{(execution.sourceStatus ? valueLabel(execution.sourceStatus) : null) ?? t("panels:execution.notObserved")}</dd>
        <dt>{t("panels:execution.finalCursor")}</dt><dd>{execution.finalCursor ?? t("panels:execution.notTerminal")}</dd>
        <dt>{t("session:composer.interrupt")}</dt><dd>{execution.interruptRequested ? t("panels:execution.requested") : t("panels:execution.notRequested")}</dd>
        <dt>{t("panels:execution.transcript")}</dt><dd>{execution.truncated ? t("panels:execution.truncated") : t("panels:execution.completeSnapshot")}</dd>
      </dl>
    </details>
  );
}

function SessionHeader({ title, contextLabel, sessionReady, connection, dockOpen, onOpenDock }: {
  readonly title?: string;
  readonly contextLabel?: string;
  readonly sessionReady: boolean;
  readonly connection: ConnectionState | "connecting";
  readonly dockOpen: boolean;
  readonly onOpenDock: () => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const label = connectionLabel(connection);
  return (
    <header className="conversation-header">
      <div className="session-heading">
        {title !== undefined ? <>
          <UiIcon name="conversation" />
          <div><h1>{title}</h1>{contextLabel ? <p>{contextLabel}</p> : null}</div>
        </> : null}
      </div>
      <div className="header-actions" data-conversation-open={title !== undefined}>
        <span className={`connection-chip ${connection}`} role="status"
          title={connection === "connecting" ? t("session:sync.live") : label}>{label}</span>
        <button type="button" aria-label={t("panels:header.shareUnavailable")} disabled>{t("panels:header.share")}</button>
        <button type="button" aria-label={t("panels:header.bottomUnavailable")} title={t("panels:header.bottomHint")} disabled><PanelIcon side="bottom" /></button>
        <button type="button" aria-label={t("panels:header.openDock")} title={t("panels:header.toggleDock")} aria-pressed={dockOpen} onClick={onOpenDock} disabled={!sessionReady}><PanelIcon side="right" /></button>
      </div>
    </header>
  );
}

function RunActivity({ run, expanded, onToggle, onSelectTask }: {
  readonly run: RunProjection;
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly onSelectTask: (taskId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const failures = run.activities.filter((activity) => activity.status === "failed").length;
  return (
    <section className="run-activity" aria-label={t("panels:activity.label")}>
      <button className="activity-summary" type="button" aria-expanded={expanded} onClick={onToggle}>
        <span className={`run-indicator ${run.status}`} aria-hidden="true">◌</span>
        <span><strong>{run.title}</strong><small>{t("panels:activity.summary", { activities: run.activities.length, failures })}</small></span>
        <span aria-hidden="true">{expanded ? "⌃" : "⌄"}</span>
      </button>
      {expanded ? (
        <ol className="activity-list">
          {run.activities.map((activity) => (
            <li key={activity.id}>
              <span className={`activity-kind ${activity.kind}`} aria-hidden="true">{activityGlyph(activity.kind)}</span>
              <div>
                <button type="button" onClick={() => onSelectTask(activity.taskId)}>{activity.label}</button>
                {activity.detail ? <code>{activity.detail}</code> : null}
              </div>
              <span>{activity.durationLabel ?? valueLabel(activity.status)}</span>
            </li>
          ))}
        </ol>
      ) : null}
    </section>
  );
}

function ChangeSetCard({ changeSet, onOpenFile, onOpenReview }: {
  readonly changeSet: ChangeSetProjection;
  readonly onOpenFile: (documentId: string, trigger: HTMLButtonElement) => void;
  readonly onOpenReview: () => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <section className="change-card" aria-label={t("panels:changes.label")}>
      <header>
        <span className="change-icon" aria-hidden="true">▣</span>
        <div><strong>{t("panels:changes.edited", { count: changeSet.files.length })}</strong><small>{changeSet.scopeLabel}</small></div>
        <span className="additions">{t("common:additions", { value: changeSet.additions })}</span><span className="deletions">{t("common:deletions", { value: changeSet.deletions })}</span>
        <button type="button" onClick={onOpenReview}>{t("panels:changes.review")}</button>
      </header>
      <div className="change-files">
        {changeSet.files.map((file) => (
          <button type="button" key={file.id} onClick={(event) => onOpenFile(file.documentId, event.currentTarget)}>
            <span>{file.path}</span><span className="additions">{t("common:additions", { value: file.additions })}</span><span className="deletions">{t("common:deletions", { value: file.deletions })}</span>
          </button>
        ))}
      </div>
      <footer><code>{changeSet.revision}</code><span>{t("panels:changes.readOnly")}</span></footer>
    </section>
  );
}

function QuickLook({ document, onClose, onOpenReview }: {
  readonly document: ReadonlyDocument;
  readonly onClose: () => void;
  readonly onOpenReview: () => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <aside className="quick-look" aria-label={t("panels:review.quickLook", { title: document.title })}>
      <header><strong>{document.title}</strong><button type="button" className="icon-close" onClick={onClose} aria-label={t("panels:review.closeQuickLook")}><UiIcon name="close" /></button></header>
      <DocumentView document={document} compact />
      <footer><button type="button" onClick={onOpenReview}>{t("panels:review.openFull")}</button></footer>
    </aside>
  );
}

interface WorkDockProps {
  readonly open: boolean;
  readonly stale: boolean;
  readonly workspacePath?: string;
  readonly temporaryWorkspace?: boolean;
  readonly inspectWorkspace?: (review: boolean) => Promise<Inspection>;
  readonly openWorkspacePath?: () => Promise<unknown>;
  readonly goalControls: ReactNode;
  readonly goalProgress: ReactNode;
  readonly tab: DockTab;
  readonly state: GuiState;
  readonly session: SessionSnapshot;
  readonly selectedDocument: ReadonlyDocument | undefined;
  readonly onClose: () => void;
  readonly onTab: (tab: DockTab) => void;
  readonly onSelectDocument: (documentId: string) => void;
  readonly onToggleActivity: (id: string) => void;
  readonly onSelectTask: (taskId: string) => void;
  readonly onSelectAgent: (agentRunId: string) => void;
}

function WorkDock(props: WorkDockProps) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const { open, stale, tab, state, session, selectedDocument, goalControls, goalProgress,
    onClose, onTab, onSelectDocument, onSelectTask, onSelectAgent } = props;
  const facet = tab === "environment" ? "workspace" : tab === "review" ? "changes" : tab;
  const available = hasCapability(state, facet);
  const live = state.remote.source.kind === "live";
  const [inspectionRefresh, setInspectionRefresh] = useState(0);
  const showRefresh = live && props.inspectWorkspace && (tab === "environment" || tab === "review");
  const showTasks = tab === "tasks" && open;
  const visibleRun = session.run ? {
    ...session.run,
    tasks: hasCapability(state, "tasks") ? session.run.tasks : [],
    agentRuns: hasCapability(state, "agents") ? session.run.agentRuns : [],
  } : null;
  return (
    <aside hidden={!open} className={`work-dock${tab === "environment" ? " dock-environment" : ""}`} aria-label={t(tab === "environment" ? "workspace:environment.summary" : "panels:dock.title")}>
      <header className="dock-header">
        <strong>{t("panels:dock.title")}</strong>
        <div className="dock-header-actions">
          {showRefresh && <button type="button" className="panel-icon-button" aria-label={t("workspace:inspection.refresh")}
            title={t("workspace:inspection.refresh")} onClick={() => setInspectionRefresh((value) => value + 1)}>
            <UiIcon name="refresh" />
          </button>}
          <button type="button" className="panel-icon-button" onClick={onClose}
            aria-label={t(tab === "environment" ? "workspace:environment.close" : "panels:dock.close")}><UiIcon name="close" /></button>
        </div>
      </header>
      <nav className="dock-tabs" aria-label={t("panels:dock.panels")}>
        {dockTabs.map((item) => (
          <button type="button" key={item.id} aria-pressed={tab === item.id} onClick={() => onTab(item.id)}>
            {t(item.label)}
          </button>
        ))}
      </nav>
      <div className="dock-content">
        <div className="dock-task-content" hidden={tab !== "tasks"}>
          {showTasks && (session.execution ? <p className="task-summary">
            {t(stale ? "panels:execution.lastKnownStatus" : "panels:execution.status",
              { status: valueLabel(session.execution.status) })}
          </p> : visibleRun && hasCapability(state, "tasks") ? <p className="task-summary">{visibleRun.title}</p> : null)}
          {goalControls}
          {showTasks && (visibleRun && hasCapability(state, "tasks") ? <>
            <RunActivity run={visibleRun} expanded={Boolean(state.local.expandedActivities[visibleRun.id])}
              onToggle={() => props.onToggleActivity(visibleRun.id)} onSelectTask={onSelectTask} />
            <TasksPanel run={visibleRun} selectedTaskId={state.local.selectedTaskId}
              onSelectTask={onSelectTask} onSelectAgent={onSelectAgent} />
          </> : !session.execution && !session.supportsInteractiveGoal && !session.supportsInteractiveGoalRecovery
            ? <UnavailablePanel label={hasCapability(state, "tasks") ? t("panels:tasks.projection")
              : t("workspace:capability.missing", { capability: capabilityLabel("tasks") })} /> : null)}
          {goalProgress}
          {showTasks && session.execution ? <ExecutionDetail execution={session.execution} stale={stale} /> : null}
        </div>
        {tab === "tasks" ? null : tab === "environment" && live ? <>
          <LiveContextPanel state={state} session={session} workspacePath={props.workspacePath}
            temporary={props.temporaryWorkspace} openPath={props.openWorkspacePath}>
            {open && props.inspectWorkspace && <WorkspaceInspection key={session.id} load={props.inspectWorkspace} review={false} workspacePath={props.workspacePath}
              revision={session.execution?.status ?? ""} refresh={inspectionRefresh} />}
          </LiveContextPanel>
        </> : tab === "review" && live
          ? open && props.inspectWorkspace
            ? <div className="inspection-review"><WorkspaceInspection key={session.id} load={props.inspectWorkspace} review
              revision={session.execution?.status ?? ""} refresh={inspectionRefresh} /></div>
            : <ReviewNotice title={t("workspace:inspection.reviewUnavailable")} detail={t("workspace:inspection.reviewNoData")} />
          : !available ? <UnavailablePanel label={facet === "workspace" ? t("workspace:capability.workspace") : t("workspace:capability.missing", { capability: capabilityLabel(facet) })} /> : <>
        {tab === "environment" ? <EnvironmentPanel state={state} session={session} /> : null}
        {tab === "agents" ? (
          <AgentsPanel run={visibleRun} selectedAgentRunId={state.local.selectedAgentRunId} onSelectAgent={onSelectAgent} onSelectTask={onSelectTask} />
        ) : null}
        {tab === "review" ? (
          <ReviewPanel session={session} selectedDocument={selectedDocument} onSelectDocument={onSelectDocument} />
        ) : null}
        </>}
      </div>
    </aside>
  );
}

function EnvironmentPanel({ state, session }: { readonly state: GuiState; readonly session: SessionSnapshot }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const workspace = state.remote.workspaces[session.workspaceId];
  return (
    <section className="panel-stack" aria-label={t("workspace:environment.details")}>
      <p className="fixture-panel-label">{t("workspace:environment.fixture")}</p>
      <dl className="detail-list">
        <div><dt>{t("workspace:environment.workspace")}</dt><dd>{workspace?.title ?? t("workspace:environment.unavailable")}</dd></div>
        <div><dt>{t("workspace:environment.root")}</dt><dd><code>{workspace?.rootLabel ?? session.context.rootLabel}</code></dd></div>
        <div><dt>{t("workspace:environment.vcs")}</dt><dd>{workspace?.vcs ? `${workspace.vcs.kind} · ${workspace.vcs.label}` : t("workspace:environment.none")}</dd></div>
      </dl>
      <details className="environment-technical">
        <summary>{t("workspace:environment.technical")}</summary>
        <dl className="detail-list">
          <div><dt>{t("workspace:environment.application")}</dt><dd><code>{session.context.applicationId}</code></dd></div>
          <div><dt>{t("workspace:environment.member")}</dt><dd><code>{session.context.muxId} / {session.context.memberId}</code></dd></div>
          <div><dt>{t("workspace:environment.session")}</dt><dd><code>{session.context.sessionId}</code></dd></div>
          <div><dt>{t("workspace:environment.generation")}</dt><dd><code>{state.remote.generation}</code></dd></div>
        </dl>
      </details>
      <h2>{t("workspace:environment.capabilities")}</h2>
      <div className="capability-list">
        {state.remote.capabilities.map((capability) => (
          <span className={`capability ${capability.availability}`} key={capability.name}>
            {capabilityLabel(capability.name)} · {capability.version ?? t("workspace:environment.unavailableValue")}
          </span>
        ))}
      </div>
    </section>
  );
}

function LiveContextPanel({ state, session, workspacePath: path, temporary, openPath, children }: {
  readonly children?: ReactNode;
  readonly openPath?: () => Promise<unknown>;
  readonly state: GuiState;
  readonly session: SessionSnapshot;
  readonly workspacePath?: string;
  readonly temporary?: boolean;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const source = state.remote.source;
  if (source.kind !== "live") return null;
  const unavailable = t("workspace:environment.unavailable");
  const workspace = state.remote.workspaces[session.workspaceId];
  const root = workspace?.rootLabel ?? path;
  const identities = [
    [t("workspace:live.fingerprint"), session.context.scopeFingerprint],
    [t("workspace:live.mux"), source.muxName ?? source.muxSpaceId],
    [t("workspace:environment.member"), session.context.memberId],
    [t("workspace:environment.session"), session.context.sessionId],
    [t("workspace:live.service"), source.serviceInstanceId],
  ] as const;
  return (
    <section className="workspace-environment" aria-label={t("workspace:live.context")}>
      <div className="workspace-location">
        <strong className="workspace-location-label">
          {temporary ? t("workspace:sidebar.temporaryChats") : workspace?.title ?? (path ? workspaceName(path) : unavailable)}
        </strong>
        {root && <CopyButton icon text={root} feedbackMs={1600}
          label={t("common:clipboard.copyValue", { label: t("workspace:environment.root") })} />}
        {root && <div className="workspace-location-path"><code title={root}>{root}</code></div>}
        {openPath && <OpenWorkspacePath open={openPath} />}
      </div>
      {!workspace && !path && !temporary ? <UnavailablePanel label={t("workspace:capability.workspace")} /> : null}
      {children}
      <details className="environment-technical">
        <summary>{t("workspace:environment.technical")}<UiIcon name="chevron-down" /></summary>
        <dl className="inspection-fields">
          <div><dt>{t("workspace:live.product")}</dt><dd>{session.context.project}</dd></div>
          <div><dt>{t("workspace:live.scope")}</dt><dd>{session.context.scope ?? unavailable}</dd></div>
          {identities.map(([label, value]) => <div key={label}>
            <dt>{label}</dt><dd>{value ? <><code title={value}>{value}</code><CopyButton icon text={value}
              label={t("common:clipboard.copyValue", { label })} /></> : unavailable}</dd>
          </div>)}
        </dl>
      </details>
    </section>
  );
}

function TasksPanel({ run, selectedTaskId, onSelectTask, onSelectAgent }: {
  readonly run: RunProjection | null;
  readonly selectedTaskId: string | null;
  readonly onSelectTask: (taskId: string) => void;
  readonly onSelectAgent: (agentRunId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  if (!run) return <UnavailablePanel label={t("panels:tasks.projection")} />;
  const selected = run.tasks.find((task) => task.id === selectedTaskId) ?? run.tasks[0];
  return (
    <section className="panel-stack" aria-label={t("panels:tasks.details")}>
      <p className="fixture-panel-label">{t("panels:tasks.summary", { status: valueLabel(run.status), count: run.tasks.length })}</p>
      <div className="task-tree">
        {run.tasks.map((task) => (
          <button type="button" key={task.id} className={task.id === selected?.id ? "selected" : ""} onClick={() => onSelectTask(task.id)}>
            <TaskStatusGlyph status={task.status} /><span>{task.title}</span>
          </button>
        ))}
      </div>
      {selected ? <TaskDetail task={selected} run={run} onSelectAgent={onSelectAgent} /> : null}
    </section>
  );
}

function TaskDetail({ task, run, onSelectAgent }: {
  readonly task: TaskProjection;
  readonly run: RunProjection;
  readonly onSelectAgent: (agentRunId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const activities = run.activities.filter((activity) => task.activityIds.includes(activity.id));
  return (
    <article className="selection-detail">
      <span className={`detail-status ${task.status}`}>{valueLabel(task.status)}</span>
      <h2>{task.title}</h2>
      <p>{t("panels:tasks.activities", { count: activities.length })}</p>
      <h3>{t("panels:tasks.assignedAgents")}</h3>
      {task.assignedAgentRunIds.map((agentRunId) => {
        const agent = run.agentRuns.find((item) => item.id === agentRunId);
        return agent ? <button type="button" key={agent.id} onClick={() => onSelectAgent(agent.id)}>{t("common:openItem", { title: agent.label })}</button> : null;
      })}
    </article>
  );
}

function AgentsPanel({ run, selectedAgentRunId, onSelectAgent, onSelectTask }: {
  readonly run: RunProjection | null;
  readonly selectedAgentRunId: string | null;
  readonly onSelectAgent: (agentRunId: string) => void;
  readonly onSelectTask: (taskId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  if (!run) return <UnavailablePanel label={t("panels:agents.projection")} />;
  const selected = run.agentRuns.find((agent) => agent.id === selectedAgentRunId) ?? run.agentRuns[0];
  return (
    <section className="panel-stack" aria-label={t("panels:agents.details")}>
      <p className="fixture-panel-label">{t("panels:agents.summary", { count: run.agentRuns.length })}</p>
      <div className="agent-tree">
        {run.agentRuns.map((agent) => (
          <button type="button" key={agent.id} className={agent.id === selected?.id ? "selected" : ""} onClick={() => onSelectAgent(agent.id)}>
            <span className={`agent-avatar ${agent.role}`} aria-hidden="true">{agent.role === "root" ? "H" : "R"}</span>
            <span><strong>{agent.label}</strong><small>{valueLabel(agent.role)} · {valueLabel(agent.status)}</small></span>
          </button>
        ))}
      </div>
      {selected ? <AgentDetail agent={selected} run={run} onSelectTask={onSelectTask} /> : null}
    </section>
  );
}

function AgentDetail({ agent, run, onSelectTask }: {
  readonly agent: AgentRunProjection;
  readonly run: RunProjection;
  readonly onSelectTask: (taskId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return (
    <article className="selection-detail">
      <span className={`detail-status ${agent.status}`}>{valueLabel(agent.status)}</span>
      <h2>{agent.label}</h2><p>{agent.summary ?? t("panels:agents.noSummary")}</p>
      <h3>{t("panels:agents.assignedTasks")}</h3>
      {agent.taskIds.map((taskId) => {
        const task = run.tasks.find((item) => item.id === taskId);
        return task ? <button type="button" key={task.id} onClick={() => onSelectTask(task.id)}>{t("common:openItem", { title: task.title })}</button> : null;
      })}
    </article>
  );
}

function ReviewPanel({ session, selectedDocument, onSelectDocument }: {
  readonly session: SessionSnapshot;
  readonly selectedDocument: ReadonlyDocument | undefined;
  readonly onSelectDocument: (documentId: string) => void;
}) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  const changeDocuments = session.changeSet?.files
    .map((file) => session.documents.find((document) => document.id === file.documentId))
    .filter((document): document is ReadonlyDocument => Boolean(document)) ?? [];
  if (!session.changeSet) return <UnavailablePanel label={t("panels:review.projection")} />;
  const visibleDocument = selectedDocument?.kind === "diff" ? selectedDocument : changeDocuments[0];
  return (
    <section className="review-panel" aria-label={t("panels:review.label")}>
      <header>
        <div><strong>{session.changeSet.scopeLabel}</strong><span><b>{t("common:additions", { value: session.changeSet.additions })}</b> <em>{t("common:deletions", { value: session.changeSet.deletions })}</em></span></div>
        <button type="button" disabled>{t("panels:review.commit")}</button>
      </header>
      <div className="review-files">
        {changeDocuments.map((document) => (
          <button type="button" key={document.id} className={document.id === visibleDocument?.id ? "selected" : ""} onClick={() => onSelectDocument(document.id)}>{document.title}</button>
        ))}
      </div>
      {visibleDocument ? <DocumentView document={visibleDocument} /> : <p>{t("panels:review.noDiff")}</p>}
    </section>
  );
}

function UnavailablePanel({ label }: { readonly label: string }) {
  const { t } = useTranslation(["session", "workspace", "panels", "common"]);
  return <div className="unavailable-panel"><strong>{t("common:unavailableTitle", { label })}</strong><p>{t("common:unavailableExplanation")}</p></div>;
}

function DocumentView({ document, compact = false }: { readonly document: ReadonlyDocument; readonly compact?: boolean }) {
  useTranslation(["session", "workspace", "panels", "common"]);
  const lines = document.content.split("\n");
  return (
    <article className={`document-view${compact ? " compact" : ""}`} aria-label={document.title}>
      <header><span>{valueLabel(document.kind)}</span><code>{document.revision}</code></header>
      <p className="document-source">{document.sourceLabel}</p>
      <pre>{lines.map((line, index) => <span className={diffLineClass(document, line)} key={`${index}-${line}`}>{line || " "}{index < lines.length - 1 ? "\n" : ""}</span>)}</pre>
    </article>
  );
}

function TaskStatusGlyph({ status }: { readonly status: TaskProjection["status"] }) {
  useTranslation(["session", "workspace", "panels", "common"]);
  const glyph = status === "completed" ? "✓" : status === "running" ? "◌" : status === "failed" ? "×" : status === "cancelled" ? "–" : "○";
  return <span className={`task-status ${status}`} aria-label={valueLabel(status)}>{glyph}</span>;
}

function diffLineClass(document: ReadonlyDocument, line: string): string {
  if (document.kind !== "diff") return "";
  if (line.startsWith("+") && !line.startsWith("+++")) return "diff-added";
  if (line.startsWith("-") && !line.startsWith("---")) return "diff-removed";
  if (line.startsWith("@@")) return "diff-hunk";
  return "";
}

function activityGlyph(kind: RunProjection["activities"][number]["kind"]): string {
  return { plan: "◴", read: "▤", command: ">_", tool: "◇", wait: "…", result: "✓" }[kind];
}

function findSelectedDocument(session: SessionSnapshot, selectedDocumentId: string | null): ReadonlyDocument | undefined {
  return session.documents.find((document) => document.id === selectedDocumentId) ?? session.documents[0];
}


const bridgeLabels = { "web-mock": "session:bridge.web-mock", locked: "session:bridge.locked", verified: "session:bridge.verified" } as const;
const valueLabels = {
  "idle": "common:status.idle",
  "running": "common:status.running",
  "waiting": "common:status.waiting",
  "interrupted": "common:status.interrupted",
  "failed": "common:status.failed",
  "completed": "common:status.completed",
  "cancelled": "common:status.cancelled",
  "pending": "common:status.pending",
  "succeeded": "common:status.succeeded",
  "streaming": "common:status.streaming",
  "root": "common:status.root",
  "subagent": "common:status.subagent",
  "assistant": "common:status.assistant",
  "user": "common:status.user",
  "diff": "common:status.diff",
  "markdown": "common:status.markdown",
  "text": "common:status.text",
  "sent": "common:status.sent",
  "complete": "common:status.complete",
  "accepted": "common:status.accepted"
} as const;
function firstPromptTitle(text: string): string {
  const characters = [...text.trim().replace(/\s+/g, " ")];
  if (characters.length <= 48) return characters.join("");
  const wordBoundary = characters.lastIndexOf(" ", 46);
  return `${characters.slice(0, wordBoundary >= 30 ? wordBoundary : 47).join("").trimEnd()}…`;
}

function displaySessionTitle(session: SessionSnapshot, title = session.title): string {
  return session.context.source === "live" && title === "New Session"
    ? i18n.t("workspace:sidebar.newSession") : title;
}

function valueLabel(value: keyof typeof valueLabels): string { return i18n.t(valueLabels[value]); }
function capabilityLabel(value: string): string {
  switch (value) {
    case "workspace": return i18n.t("workspace:environment.workspace");
    case "tasks": return i18n.t("panels:dock.tasks");
    case "agents": return i18n.t("panels:dock.agents");
    case "artifacts": return i18n.t("workspace:environment.artifacts");
    case "changes": return i18n.t("panels:changes.review");
    default: return value;
  }
}



function connectionLabel(connection: ConnectionState | "connecting"): string {
  switch (connection) {
    case "fixture-offline": return i18n.t("workspace:sidebar.offline");
    case "connecting": return i18n.t("common:connection.connecting");
    case "connected": return i18n.t("common:connection.connected");
    case "disconnected": return i18n.t("common:connection.disconnected");
    case "resync-required": return i18n.t("common:connection.resync");
  }
}

function App({ account }: { account?: OfflineAccount | null }) {
  const client = useMemo(() => createNativeLiveClient(), []);
  return <HarnessGui client={client} account={account} />;
}

export default App;
