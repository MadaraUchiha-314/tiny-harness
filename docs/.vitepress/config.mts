import { existsSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { type DefaultTheme } from "vitepress";
import { withMermaid } from "vitepress-plugin-mermaid";

// srcDir is docs/ itself; this file sits in docs/.vitepress/.
const docsRoot = dirname(dirname(fileURLToPath(import.meta.url)));

const REPO = "https://github.com/MadaraUchiha-314/tiny-harness";

function markdownIn(dir: string): string[] {
  const abs = join(docsRoot, dir);
  if (!existsSync(abs)) return [];
  return readdirSync(abs)
    .filter((f) => f.endsWith(".md"))
    .map((f) => f.replace(/\.md$/, ""))
    .sort();
}

function title(slug: string): string {
  const words = slug.replace(/-/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

// One sidebar group per tree; `index` names the tree's landing page, listed first.
function treeItems(dir: string, index: string): DefaultTheme.SidebarItem[] {
  const pages = markdownIn(dir).filter((slug) => slug !== index);
  return [
    { text: "Overview", link: `/${dir}/${index}` },
    ...pages.map((slug) => ({ text: title(slug), link: `/${dir}/${slug}` })),
  ];
}

// Spec folders are generated from the filesystem so new work items appear without nav
// edits; files are listed in the-loop's phase order, evidence last.
const SPEC_FILE_ORDER: [string, string][] = [
  ["brainstorm", "Brainstorm"],
  ["requirements", "Requirements"],
  ["bugfix", "Bugfix"],
  ["design", "Design"],
  ["testing-plan", "Testing plan"],
  ["tasks", "Tasks"],
  ["context", "Context"],
];

function issueNumber(dir: string): number {
  const m = dir.match(/(\d+)$/);
  return m ? Number(m[1]) : Number.MAX_SAFE_INTEGER;
}

function specItems(): DefaultTheme.SidebarItem[] {
  const specsDir = join(docsRoot, "specs");
  return readdirSync(specsDir)
    .filter((d) => statSync(join(specsDir, d)).isDirectory())
    .sort((a, b) => issueNumber(b) - issueNumber(a))
    .map((dir) => {
      const present = new Set(markdownIn(`specs/${dir}`));
      const items: DefaultTheme.SidebarItem[] = SPEC_FILE_ORDER.filter(([slug]) =>
        present.has(slug),
      ).map(([slug, text]) => ({ text, link: `/specs/${dir}/${slug}` }));
      const evidence = markdownIn(`specs/${dir}/evidence`);
      if (evidence.length > 0) {
        items.push({
          text: "Evidence",
          collapsed: true,
          items: evidence.map((slug) => ({
            text: title(slug),
            link: `/specs/${dir}/evidence/${slug}`,
          })),
        });
      }
      return { text: dir, collapsed: true, items };
    });
}

const CLI: DefaultTheme.SidebarItem[] = [
  { text: "Quickstart", link: "/cli/" },
  { text: "Use the TUI", link: "/cli/tui" },
];

const SDK: DefaultTheme.SidebarItem[] = [
  { text: "Quickstart", link: "/sdk/" },
  { text: "Add tools, commands and skills", link: "/sdk/extend" },
  { text: "Example: support agent", link: "/sdk/example" },
  { text: "Deploy", link: "/sdk/deploy" },
];

const CONFIGURATION: DefaultTheme.SidebarItem[] = [
  { text: "Overview", link: "/configuration/" },
  { text: "Temporal", link: "/configuration/temporal" },
  { text: "Models", link: "/configuration/models" },
  { text: "Server", link: "/configuration/server" },
  { text: "Plugins and other agents", link: "/configuration/plugins-and-agents" },
  { text: "Storage", link: "/configuration/storage" },
  { text: "Observability", link: "/configuration/observability" },
  { text: "Tuning", link: "/configuration/tuning" },
];

const A2A: DefaultTheme.SidebarItem[] = [
  { text: "Extensions", link: "/a2a/extensions" },
  { text: "Task extension v1", link: "/a2a/ext/task/v1" },
  { text: "Channel extension v1", link: "/a2a/ext/channel/v1" },
  { text: "Status extension v1", link: "/a2a/ext/status/v1" },
  { text: "Commands extension v1", link: "/a2a/ext/commands/v1" },
];

// The contributor sidebar: everything that is not a user guide.
const DEVELOPER: DefaultTheme.SidebarItem[] = [
  {
    text: "Developer guide",
    items: [
      { text: "Set up and checks", link: "/develop/" },
      { text: "Tech stack", link: "/develop/tech-stack" },
      { text: "Releasing", link: "/develop/releasing" },
      { text: "Write documentation", link: "/develop/writing-docs" },
    ],
  },
  { text: "Architecture", collapsed: false, items: treeItems("architecture", "architecture") },
  { text: "Capabilities", collapsed: true, items: treeItems("capabilities", "capabilities") },
  { text: "A2A reference", collapsed: true, items: A2A },
  { text: "Decisions", collapsed: true, items: treeItems("decisions", "decisions") },
  { text: "Learnings", collapsed: true, items: treeItems("learnings", "learnings") },
  { text: "Specs", collapsed: true, items: [{ text: "Overview", link: "/specs/" }, ...specItems()] },
];

// withMermaid renders ```mermaid fences as diagrams (the-loop's specs use them throughout).
export default withMermaid({
  title: "tiny-harness",
  description: "A tiny agent harness",
  base: "/tiny-harness/",
  cleanUrls: true,
  lastUpdated: true,
  // The-loop's capability docs link a work item's spec folder (`../specs/<id>/`), which
  // has no index page; those links are intentional and point at a folder of pages.
  ignoreDeadLinks: [/\/specs\/[^/]+\/(index)?$/],
  themeConfig: {
    nav: [
      { text: "CLI", link: "/cli/" },
      { text: "SDK", link: "/sdk/" },
      { text: "Configuration", link: "/configuration/" },
      { text: "Developers", link: "/develop/" },
    ],
    // One sidebar per reader: users never scroll past the-loop's records.
    sidebar: {
      "/cli/": [{ text: "CLI guide", items: CLI }, { text: "Configuration", items: CONFIGURATION }],
      "/sdk/": [
        { text: "SDK guide", items: SDK },
        { text: "Configuration", items: CONFIGURATION },
        { text: "A2A reference", collapsed: true, items: A2A },
      ],
      "/configuration/": [
        { text: "Configuration", items: CONFIGURATION },
        { text: "Guides", items: [{ text: "CLI quickstart", link: "/cli/" }, { text: "SDK quickstart", link: "/sdk/" }] },
      ],
      "/a2a/": [{ text: "A2A reference", items: A2A }, { text: "SDK guide", items: SDK }],
      "/": DEVELOPER,
    },
    search: { provider: "local" },
    socialLinks: [{ icon: "github", link: REPO }],
    editLink: {
      pattern: `${REPO}/edit/main/docs/:path`,
      text: "Edit this page on GitHub",
    },
    outline: [2, 3],
  },
});
