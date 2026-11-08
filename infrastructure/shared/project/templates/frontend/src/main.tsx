import React from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { DesignSystemProvider } from "./design-system";
import "./style.css";

createRoot(document.getElementById("root")!).render(<React.StrictMode><DesignSystemProvider><App /></DesignSystemProvider></React.StrictMode>);
