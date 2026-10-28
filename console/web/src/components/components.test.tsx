import { fireEvent, render, screen, within } from "@testing-library/react";
import { DataTable, FreshnessBadge, SeverityBadge, StateBadge } from "./ui";
import { MarkdownView, safeHref } from "./viewers";

describe("status semantics never rely on colour alone", () => {
  it("state badges carry a text label and mark inferred states", () => {
    const { rerender } = render(<StateBadge state="succeeded" basis="recorded" />);
    expect(screen.getByText("done")).toBeInTheDocument();
    rerender(<StateBadge state="crashed" basis="inferred" />);
    expect(screen.getByText("crashed?")).toBeInTheDocument();
    expect(screen.getByTitle(/Inferred from the run directory/)).toBeInTheDocument();
    rerender(<StateBadge state={null} />);
    expect(screen.getByText("never run")).toBeInTheDocument();
  });
  it("freshness and severity badges are labelled", () => {
    render(<><FreshnessBadge value="unsynced" /><FreshnessBadge value="unknown" /><SeverityBadge sev="critical" /></>);
    expect(screen.getByText("out of date")).toBeInTheDocument();
    expect(screen.getByText("provenance unrecorded")).toBeInTheDocument();
    expect(screen.getByText("Critical")).toBeInTheDocument();
  });
});

describe("generated content is untrusted", () => {
  it("allows only safe link schemes", () => {
    expect(safeHref("https://example.com")).toBe("https://example.com");
    expect(safeHref("#section-5")).toBe("#section-5");
    expect(safeHref("./brd.md")).toBe("./brd.md");
    expect(safeHref("mailto:x@y.z")).toBe("mailto:x@y.z");
    expect(safeHref("javascript:alert(1)")).toBeUndefined();
    expect(safeHref(" JaVaScRiPt:alert(1)")).toBeUndefined();
    expect(safeHref("data:text/html,<script>")).toBeUndefined();
    expect(safeHref("vbscript:x")).toBeUndefined();
  });
  it("renders raw HTML in Markdown as inert text, not elements", () => {
    const { container } = render(<MarkdownView text={'# Title\n\n<script>window.pwned=1</script><img src=x onerror="alert(1)">\n\n[click](javascript:alert(1)) and [ok](https://example.com)'} />);
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    const links = container.querySelectorAll("a");
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("https://example.com");
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
    expect(screen.getByTitle("link removed: unsafe scheme")).toHaveTextContent("click");
  });
});

describe("DataTable", () => {
  const rows = [{ id: "b", n: 2 }, { id: "a", n: 10 }, { id: "c", n: 1 }];
  it("sorts by a column and exposes aria-sort", () => {
    render(<DataTable rows={rows} rowKey={(r) => r.id} caption="t" columns={[
      { key: "id", header: "Id", render: (r) => r.id, sort: (r) => r.id },
      { key: "n", header: "N", num: true, render: (r) => String(r.n), sort: (r) => r.n }]} />);
    const order = () => screen.getAllByRole("row").slice(1).map((r) => within(r).getAllByRole("cell")[0].textContent);
    expect(order()).toEqual(["b", "a", "c"]);
    fireEvent.click(screen.getByRole("button", { name: /N/ }));
    expect(order()).toEqual(["c", "b", "a"]);
    expect(screen.getByRole("columnheader", { name: /N/ })).toHaveAttribute("aria-sort", "ascending");
    fireEvent.click(screen.getByRole("button", { name: /N/ }));
    expect(order()).toEqual(["a", "b", "c"]);
  });
  it("shows an empty state", () => {
    render(<DataTable rows={[]} rowKey={() => "x"} columns={[]} empty="Nothing here" />);
    expect(screen.getByText("Nothing here")).toBeInTheDocument();
  });
});
