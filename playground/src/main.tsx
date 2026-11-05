import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";
const Classroom = React.lazy(() => import("./classroom/Classroom"));
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {window.location.pathname === "/classroom" ? (
      <React.Suspense
        fallback={<div style={{ padding: 40 }}>正在打开课堂练习室…</div>}
      >
        <Classroom />
      </React.Suspense>
    ) : (
      <App />
    )}
  </React.StrictMode>,
);
