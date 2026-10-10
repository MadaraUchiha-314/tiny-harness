import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App, configFromLocation } from "./App";
import "./styles.css";

const root = document.getElementById("root");
if (root === null) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <App config={configFromLocation()} />
  </StrictMode>,
);
