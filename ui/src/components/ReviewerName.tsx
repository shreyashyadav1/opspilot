import { uiStyles } from "./ui";

/** Shown next to a reviewer name the API took on trust because it ran without API keys. */
export const UNVERIFIED = "name not verified";

/**
 * A reviewer's name as recorded with a decision. Without API keys anyone can type any name, so
 * a name the API did not check from a key says so instead of reading like a signature.
 */
export function ReviewerName({ name, authenticated }: { name: string; authenticated?: boolean }) {
  if (authenticated === true) return <>{name}</>;
  return (
    <>
      {name}{" "}
      <span
        className={uiStyles.unverified}
        title="The API ran without keys, so this name was typed in and not checked."
      >
        ({UNVERIFIED})
      </span>
    </>
  );
}
