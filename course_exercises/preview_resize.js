(() => {
  const runId = __CLASSROOM_RUN_ID__;
  let reportedHeight = 0;
  let pending = false;

  function measure() {
    pending = false;
    const root = document.documentElement;
    const body = document.body;
    if (!body) return;
    const height = Math.ceil(Math.max(root.scrollHeight, body.scrollHeight));
    if (height === reportedHeight) return;
    reportedHeight = height;
    parent.postMessage({ type: "classroom-preview-size", runId, height }, "*");
  }

  function schedule() {
    if (pending) return;
    pending = true;
    setTimeout(measure, 100);
  }

  function start() {
    const observer = new ResizeObserver(schedule);
    observer.observe(document.documentElement);
    if (document.body) observer.observe(document.body);
    const mutations = new MutationObserver(schedule);
    mutations.observe(document.documentElement, { childList: true, subtree: true, characterData: true });
    window.addEventListener("resize", schedule);
    document.addEventListener("load", schedule, true);
    if (document.fonts) document.fonts.ready.then(schedule);
    schedule();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start, { once: true });
  else start();
})();
