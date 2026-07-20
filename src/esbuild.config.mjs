import { build } from "esbuild";

await build({
  entryPoints: ["index.ts"],
  bundle: true,
  format: "esm",
  target: "es2022",
  outfile: "../custom_components/jinjaboard/www/jinjaboard-strategy.js",
  minify: process.env.NODE_ENV === "production",
});
