/** Not-found + friendly error state (SPEC §29, §33.22). */

import { Link, useNavigate } from "react-router-dom";
import { Button } from "../components/ui";
import { IconSearch } from "../components/ui/icons";
import layout from "../layouts/layout.module.css";

export function NotFoundPage() {
  const navigate = useNavigate();
  return (
    <div className={layout.section} style={{ maxWidth: 560, margin: "48px auto" }}>
      <div>
        <div style={{ textAlign: "center", padding: "24px 0" }}>
          <div style={{ color: "var(--text-tertiary)", marginBottom: 12 }}>
            <IconSearch size={36} />
          </div>
          <h1 className={layout.pageTitle} style={{ fontSize: 22 }}>
            Page not found
          </h1>
          <p className={layout.muted} style={{ margin: "8px 0 20px" }}>
            The page you asked for does not exist. It may have been moved, or the link is
            outdated — nothing was changed on the server.
          </p>
          <div className={layout.row} style={{ justifyContent: "center" }}>
            <Button variant="secondary" onClick={() => navigate(-1)}>
              Go back
            </Button>
            <Link to="/">
              <Button variant="primary">Open Overview</Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
