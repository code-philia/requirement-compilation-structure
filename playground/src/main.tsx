import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
const Classroom = React.lazy(() => import("./classroom/Classroom"));
const CompareRuns = React.lazy(() => import("./components/CompareRuns"));
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname === "/classroom" ? (
      <React.Suspense
        fallback={<div style={{ padding: 40 }}>正在打开课堂练习室…</div>}
      >
        <Classroom />
      </React.Suspense>
    ) : window.location.pathname === "/compare" ? (
      <React.Suspense
        fallback={<div style={{ padding: 40 }}>正在打开运行对比…</div>}
      >
        <CompareRuns />
      </React.Suspense>
    ) : (
      <App />
    )}
  </React.StrictMode>,
);
