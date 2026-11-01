import fs from "node:fs";
import path from "node:path";
import ts from "typescript";
function sources(root: string): string[] {
  return fs
    .readdirSync(root, { withFileTypes: true })
    .flatMap((e) =>
      e.isDirectory() && !["node_modules", "server"].includes(e.name)
        ? sources(path.join(root, e.name))
        : e.isFile() && /\.tsx?$/.test(e.name) && !e.name.includes(".test.")
          ? [path.join(root, e.name)]
          : [],
    );
}
test("browser callers retain CSRF adapter and client directive prologue", () => {
  const root = path.resolve(__dirname, ".."),
    missing: string[] = [];
  for (const file of sources(root)) {
    const text = fs.readFileSync(file, "utf8"),
      tree = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true);
    for (const node of tree.statements) {
      if (
        ts.isExpressionStatement(node) &&
        ts.isStringLiteral(node.expression) &&
        node.expression.text === "use client"
      )
        expect(
          tree.statements
            .slice(0, tree.statements.indexOf(node))
            .every(
              (s) =>
                ts.isExpressionStatement(s) && ts.isStringLiteral(s.expression),
            ),
        ).toBe(true);
    }
    if (path.basename(file) !== "browserTransport.ts" && /\bfetch\(/.test(text))
      missing.push(path.relative(root, file));
  }
  expect(missing).toEqual([]);
});
