import { DemoFaultPanel } from "@/components/DemoFaultPanel";
import { IncidentList } from "@/components/IncidentList";
import { StartInvestigationForm } from "@/components/StartInvestigationForm";

import styles from "./page.module.css";

export default function IncidentsPage() {
  return (
    <div className={styles.page}>
      <div className={styles.intro}>
        <h1>Incidents</h1>
        <p>
          Alerts the agent has investigated. It reads telemetry on its own; anything that changes
          the system waits here for a person to approve it.
        </p>
      </div>
      <div className={styles.columns}>
        <div className={styles.list}>
          <IncidentList />
        </div>
        <aside className={styles.aside} aria-label="Actions">
          <StartInvestigationForm />
          <DemoFaultPanel />
        </aside>
      </div>
    </div>
  );
}
