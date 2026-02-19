import { useEffect, useMemo, useState } from "react";

const REVIEW_ROUTE_RE = /^\/documents\/(\d+)\/review\/?$/i;

export function parseAppRoute(pathname) {
  const match = REVIEW_ROUTE_RE.exec(pathname || "/");
  if (!match) {
    return { type: "home" };
  }

  return {
    type: "review",
    documentId: Number(match[1]),
  };
}

export function navigateTo(pathname) {
  if (window.location.pathname === pathname) {
    return;
  }
  window.history.pushState({}, "", pathname);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export function useAppRoute() {
  const [pathname, setPathname] = useState(window.location.pathname);

  useEffect(() => {
    const handlePathChange = () => setPathname(window.location.pathname);
    window.addEventListener("popstate", handlePathChange);
    return () => {
      window.removeEventListener("popstate", handlePathChange);
    };
  }, []);

  return useMemo(() => parseAppRoute(pathname), [pathname]);
}
