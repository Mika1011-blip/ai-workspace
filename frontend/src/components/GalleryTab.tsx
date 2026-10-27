import { useEffect, useState } from "react";
import { listProjects, type Project } from "../api";

/** The showroom: finished videos. Artifacts and decisions still open in the
 * gallery page until that view is rebuilt here. */
export default function GalleryTab() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { listProjects().then(setProjects).catch((e) => setError((e as Error).message)); }, []);
  if (error) return <p className="error">{error}</p>;
  if (!projects) return <p className="muted">Loading…</p>;
  return (
    <div className="gallery">
      <h2>Showroom</h2>
      {projects.length === 0 && <p className="muted">No projects yet. Ask the master for a video and it will appear here.</p>}
      <ul className="projects">
        {projects.map((p) => (
          <li key={p.slug} className="project">
            {p.has_final ? (
              <video controls preload="metadata" src={`/projects/${p.slug}/final.mp4`} poster={p.has_preview ? `/projects/${p.slug}/preview.jpg` : undefined} />
            ) : <div className="poster muted">no video yet</div>}
            <div>
              <strong>{p.title}</strong>
              <p className="muted small">{p.slug} · {p.status}</p>
              <p className="small">
                <a href={`/gallery#/p/${p.slug}`} target="_blank" rel="noreferrer">artifacts</a>
                {p.has_final && <> · <a href={`/projects/${p.slug}/download`} download={`${p.slug}.zip`}>download zip</a></>}
              </p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
