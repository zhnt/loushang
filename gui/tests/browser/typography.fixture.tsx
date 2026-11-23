import { createRoot } from "react-dom/client";
import { HarnessGui } from "../../src/App";
import type { HarnessClientUiPort } from "../../src/client/model";
import { TEMPORARY_WORKSPACE, type ManagedProjectNavigation, type ProjectChat } from "../../src/client/projectDirectory";
import { initializeI18n } from "../../src/i18n";
import { createMockAppClient } from "../support/mockAppClient";

const project = "/work/桌面 GUI";
const chat = (id: string, title: string, pinned = false): ProjectChat => ({ id, title, scope: "fixture", pinned });
const title = "项目排版 GUI Review";
const temporary = [
  chat("zh", "你好"),
  chat("en", "New Session review"),
  chat("mixed", "Mixed 文案 · 版本 2.0"),
  chat("long-zh", "这是用于验证长会话标题省略和单行字形清晰度的中文标题"),
  chat("long-en", "A long English session title for checking readability and truncation"),
];

async function mount() {
  const seed = await createMockAppClient().snapshot();
  const sameText = "中文与 English 混排，Version 2.0 和数字 128 清晰易读。";
  const session = {
    ...seed.sessions[0], id: "mixed", title, status: "idle" as const, run: null, changeSet: null,
    supportsInteractiveGoal: true as const,
    messages: [
      { id: "prompt", role: "user" as const, phase: "complete" as const, content: sameText },
      { id: "reply", role: "assistant" as const, phase: "complete" as const,
        content: `## 阅读布局 · Markdown\n\n${sameText}\n\n使用 \`cargo test\`。\n\n\`\`\`text\nModel ID: desktop-review\n\`\`\`` },
    ],
  };
  const models = { currentId: "review", models: [{
    id: "review", provider: "local", endpointId: "fixture", modelId: "Desktop 文案", label: "Desktop 文案", supportsThinking: false,
  }] };
  const client: HarnessClientUiPort = {
    snapshot: async () => ({
      ...seed, connection: "connected", sessions: [session], selectedSessionId: session.id,
      source: { kind: "live", serviceInstanceId: "typography", muxSpaceId: "typography", connectionEpoch: "1" },
    }),
    subscribe: () => () => {},
    submitText: async ({ submissionId }) => ({ accepted: false, submissionId }),
    interrupt: async () => ({ accepted: false }),
    sessionModels: async () => models,
    sessionResource: async () => { throw new Error("Fixture has no stored resources"); },
    pickClientDirectory: async () => null,
    createInteractiveGoal: async () => null,
    interactiveGoalStatus: async () => ({
      availability: "ready", goalId: null, status: null, revision: null, epoch: null, executionUnresolved: null,
    }),
  };
  const navigation: ManagedProjectNavigation = {
    hostKey: "typography", available: true, pending: false, error: false, folderInput: false,
    directory: {
      projects: [{ path: project, sessions: [chat("pinned", "置顶 · Pinned", true)] }],
      temporarySessions: temporary,
    },
    selection: { workspace: TEMPORARY_WORKSPACE, id: session.id },
    openFolder: () => {}, closeFolder: () => {}, register: async () => false,
    createChat: async () => null, togglePin: () => {}, select: () => {},
  };
  await initializeI18n();
  createRoot(document.getElementById("root")!).render(
    <HarnessGui client={client} projectNavigation={navigation} />,
  );
}

void mount();
