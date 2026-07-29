import React from "react";
import ReactDOM from "react-dom/client";
import "./design-system/styles.css"; // tokens + fonts + thème dark-first
import "./index.css";
import { App } from "./App";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
