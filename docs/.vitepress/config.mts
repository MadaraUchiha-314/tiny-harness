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
      { text: "Guide", link: "/guide/tech-stack" },
      { text: "Architecture", link: "/architecture/architecture" },
      { text: "Capabilities", link: "/capabilities/capabilities" },
      { text: "Decisions", link: "/decisions/decisions" },
      { text: "Specs", link: "/specs/" },
    ],
    sidebar: [
      {
        text: "Guide",
        items: [
          { text: "Tech stack", link: "/guide/tech-stack" },
          { text: "Local development", link: "/guide/local-development" },
          { text: "Releasing", link: "/guide/releasing" },
        ],
      },
      { text: "Architecture", collapsed: false, items: treeItems("architecture", "architecture") },
      { text: "Capabilities", collapsed: false, items: treeItems("capabilities", "capabilities") },
      { text: "Decisions", collapsed: true, items: treeItems("decisions", "decisions") },
      { text: "Learnings", collapsed: true, items: treeItems("learnings", "learnings") },
      { text: "Specs", collapsed: true, items: [{ text: "Overview", link: "/specs/" }, ...specItems()] },
    ],
    search: { provider: "local" },
    socialLinks: [{ icon: "github", link: REPO }],
    editLink: {
      pattern: `${REPO}/edit/main/docs/:path`,
      text: "Edit this page on GitHub",
    },
    outline: [2, 3],
  },
});
