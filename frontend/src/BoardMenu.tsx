import {
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import {
  commandArchivedCard,
  commandArchivedList,
  createBoardLabel,
  deleteBoardLabel,
  getBoardActivity,
  getBoardArchive,
  renameBoard,
  setBoardBackgroundColor,
  updateBoardLabel,
  uploadBoardBackground,
} from "./api";
import type {
  BoardActivityRow,
  BoardArchivePayload,
  BoardLabel,
  BoardSnapshot,
  SessionUser,
} from "./types";
import { errorMessage, formatDateTime } from "./ui";

type MenuView =
  | "main"
  | "visibility"
  | "settings"
  | "background"
  | "colors"
  | "labels"
  | "activity"
  | "archived";

const BACKGROUNDS = [
  { key: "bubbles", emoji: "🫧", label: "Deep navy", gradient: "linear-gradient(112deg, #192e4d 0%, #163057 100%)" },
  { key: "snow", emoji: "❄️", label: "Blue sky", gradient: "linear-gradient(112deg, #197eda 0%, #299ace 100%)" },
  { key: "wave", emoji: "🌊", label: "Ocean blue", gradient: "linear-gradient(112deg, #0b54bb 0%, #0a4497 100%)" },
  { key: "magic", emoji: "🔮", label: "Indigo plum", gradient: "linear-gradient(112deg, #463b7b 0%, #8c468c 100%)" },
  { key: "rainbow", emoji: "🌈", label: "Purple pink", gradient: "linear-gradient(112deg, #9664c2 0%, #bb6cbf 100%)" },
  { key: "peach", emoji: "🍑", label: "Orange peach", gradient: "linear-gradient(112deg, #ea6537 0%, #f2863a 100%)" },
  { key: "blossom", emoji: "🌸", label: "Pink coral", gradient: "linear-gradient(112deg, #ed749e 0%, #f27483 100%)" },
  { key: "earth", emoji: "🌎", label: "Green teal", gradient: "linear-gradient(112deg, #33987f 0%, #4ab0aa 100%)" },
  { key: "alien", emoji: "👽", label: "Slate blue", gradient: "linear-gradient(112deg, #3d4e6b 0%, #2c3e5d 100%)" },
  { key: "wizard", emoji: "🧙", label: "Rust red", gradient: "linear-gradient(112deg, #632912 0%, #892915 100%)" },
] as const;

const LABEL_COLORS: BoardLabel["color"][] = [
  "green", "yellow", "orange", "red", "purple", "blue",
];

function Header({
  title,
  canGoBack,
  onBack,
  onClose,
}: {
  title: string;
  canGoBack: boolean;
  onBack: () => void;
  onClose: () => void;
}) {
  return (
    <header className="trello-board-menu__header">
      <button
        className="trello-board-menu__back"
        type="button"
        aria-label="Back"
        onClick={onBack}
        disabled={!canGoBack}
      >
        {canGoBack ? "‹" : ""}
      </button>
      <strong>{title}</strong>
      <button
        className="trello-board-menu__close"
        type="button"
        aria-label="Close board menu"
        onClick={onClose}
      >
        ×
      </button>
    </header>
  );
}

function TrelloMenuIcon({
  kind,
}: {
  kind: "settings" | "background" | "labels" | "activity" | "archive";
}) {
  const common = {
    width: 18,
    height: 18,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.75,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    "data-menu-icon": kind,
  };

  if (kind === "settings") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="3.25" />
        <path d="M19.2 13.1a7.8 7.8 0 0 0 .05-2.2l2-1.55-2-3.45-2.48 1a8.2 8.2 0 0 0-1.9-1.1L14.5 3h-5l-.38 2.8a8.2 8.2 0 0 0-1.9 1.1l-2.47-1-2 3.45 2 1.55a7.8 7.8 0 0 0 .05 2.2l-2.05 1.55 2 3.45 2.55-1.02a8.5 8.5 0 0 0 1.82 1.05L9.5 21h5l.38-2.87a8.5 8.5 0 0 0 1.82-1.05l2.55 1.02 2-3.45-2.05-1.55Z" />
      </svg>
    );
  }
  if (kind === "background") {
    return (
      <span className="trello-board-menu__background-icon" data-menu-icon={kind}>
        <span />
      </span>
    );
  }
  if (kind === "labels") {
    return (
      <svg {...common}>
        <path d="M4 7.5V5.8A1.8 1.8 0 0 1 5.8 4h6.4l7.6 7.6a1.8 1.8 0 0 1 0 2.55l-5.65 5.65a1.8 1.8 0 0 1-2.55 0L4 12.2V7.5Z" />
        <circle cx="8.1" cy="8.1" r="1.15" />
      </svg>
    );
  }
  if (kind === "activity") {
    return (
      <svg {...common}>
        <path d="M4.3 8.4A8.1 8.1 0 1 1 4 14" />
        <path d="M4.2 4.8v4.4h4.4" />
        <path d="M12 7.7v4.8l3.2 1.9" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M4 7.5h16v12H4z" />
      <path d="M3 4.5h18v3H3zM9.2 11.5h5.6" />
    </svg>
  );
}

function MenuRow({
  icon,
  label,
  detail,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  detail?: string;
  onClick: () => void;
}) {
  return (
    <button className="trello-board-menu__row" type="button" onClick={onClick}>
      <span className="trello-board-menu__icon" aria-hidden="true">{icon}</span>
      <span className="trello-board-menu__row-copy">
        <strong>{label}</strong>
        {detail && <small>{detail}</small>}
      </span>
      <span className="trello-board-menu__chevron" aria-hidden="true">›</span>
    </button>
  );
}

function LabelEditor({
  label,
  snapshot,
  onSaved,
  onCancel,
}: {
  label: BoardLabel | null;
  snapshot: BoardSnapshot;
  onSaved: () => Promise<void>;
  onCancel: () => void;
}) {
  const [color, setColor] = useState<BoardLabel["color"]>(label?.color ?? "green");
  const [name, setName] = useState(label?.name ?? "");
  const [description, setDescription] = useState(label?.description ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (label) {
        await updateBoardLabel(
          snapshot.board.id,
          label.id,
          { color, name: name.trim(), description: description.trim() },
          snapshot.revision,
        );
      } else {
        await createBoardLabel(
          snapshot.board.id,
          { color, name: name.trim(), description: description.trim() },
          snapshot.revision,
        );
      }
      await onSaved();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!label || busy) return;
    if (!window.confirm("Delete this label? It will be removed from every card using it.")) return;
    setBusy(true);
    setError("");
    try {
      await deleteBoardLabel(snapshot.board.id, label.id, snapshot.revision);
      await onSaved();
    } catch (caught) {
      setError(errorMessage(caught));
      setBusy(false);
    }
  }

  return (
    <form className="trello-label-editor" onSubmit={save}>
      {error && <div className="trello-menu-error">{error}</div>}
      <label>
        Label name
        <input
          autoFocus
          value={name}
          maxLength={100}
          placeholder="e.g. Waiting for client"
          onChange={(event) => setName(event.target.value)}
        />
      </label>
      <label>
        Description / meaning
        <textarea
          value={description}
          maxLength={500}
          rows={3}
          placeholder="Explain when the team should use this label."
          onChange={(event) => setDescription(event.target.value)}
        />
      </label>
      <div>
        <span className="trello-label-editor__caption">Color</span>
        <div className="trello-label-editor__colors">
          {LABEL_COLORS.map((item) => (
            <button
              key={item}
              type="button"
              className="trello-label-color"
              data-label-color={item}
              aria-label={`${item} label`}
              aria-pressed={color === item}
              onClick={() => setColor(item)}
            >
              {color === item ? "✓" : ""}
            </button>
          ))}
        </div>
      </div>
      <div className="trello-label-editor__actions">
        <button className="button trello-primary-button" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        <button className="button button--ghost" type="button" disabled={busy} onClick={onCancel}>
          Cancel
        </button>
        {label && (
          <button className="button button--danger" type="button" disabled={busy} onClick={() => void remove()}>
            Delete
          </button>
        )}
      </div>
    </form>
  );
}

export function BoardMenu({
  snapshot,
  currentUser,
  onClose,
  onChanged,
  onOpenMembers,
}: {
  snapshot: BoardSnapshot;
  currentUser: SessionUser;
  onClose: () => void;
  onChanged: () => Promise<void>;
  onOpenMembers: () => void;
}) {
  const canManage = currentUser.is_admin || snapshot.membership.role === "MANAGER";
  const [view, setView] = useState<MenuView>("main");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [labelSearch, setLabelSearch] = useState("");
  const [editingLabel, setEditingLabel] = useState<BoardLabel | null | undefined>(undefined);
  const [activity, setActivity] = useState<BoardActivityRow[]>([]);
  const [activityFilter, setActivityFilter] = useState<"all" | "comment">("all");
  const [activityBusy, setActivityBusy] = useState(false);
  const [archive, setArchive] = useState<BoardArchivePayload | null>(null);
  const [archiveBusy, setArchiveBusy] = useState(false);
  const [archiveTab, setArchiveTab] = useState<"cards" | "lists">("cards");
  const [archiveSearch, setArchiveSearch] = useState("");
  const [settingsName, setSettingsName] = useState(snapshot.board.name);
  const fileRef = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [onClose]);

  useEffect(() => {
    setSettingsName(snapshot.board.name);
  }, [snapshot.board.name]);

  useEffect(() => {
    if (view !== "activity") return;
    setActivityBusy(true);
    setError("");
    void getBoardActivity(snapshot.board.id)
      .then((result) => setActivity(result.activity))
      .catch((caught) => setError(errorMessage(caught)))
      .finally(() => setActivityBusy(false));
  }, [snapshot.board.id, snapshot.revision, view]);

  useEffect(() => {
    if (view !== "archived") return;
    setArchiveBusy(true);
    setError("");
    void getBoardArchive(snapshot.board.id)
      .then(setArchive)
      .catch((caught) => setError(errorMessage(caught)))
      .finally(() => setArchiveBusy(false));
  }, [snapshot.board.id, snapshot.revision, view]);

  const filteredLabels = useMemo(() => {
    const query = labelSearch.trim().toLowerCase();
    const labels = snapshot.labels ?? [];
    if (!query) return labels;
    return labels.filter((label) =>
      `${label.name} ${label.description} ${label.color}`.toLowerCase().includes(query),
    );
  }, [labelSearch, snapshot.labels]);

  const filteredActivity = useMemo(
    () => activityFilter === "all" ? activity : activity.filter((row) => row.category === "comment"),
    [activity, activityFilter],
  );

  const filteredCards = useMemo(() => {
    const query = archiveSearch.trim().toLowerCase();
    return (archive?.cards ?? []).filter((card) =>
      `${card.title} ${card.column_name} ${card.owner_username ?? ""}`.toLowerCase().includes(query),
    );
  }, [archive, archiveSearch]);

  const filteredLists = useMemo(() => {
    const query = archiveSearch.trim().toLowerCase();
    return (archive?.lists ?? []).filter((list) => list.name.toLowerCase().includes(query));
  }, [archive, archiveSearch]);

  async function chooseBackground(key: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await setBoardBackgroundColor(snapshot.board.id, key, snapshot.revision);
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function uploadBackground(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || busy) return;
    setBusy(true);
    setError("");
    try {
      await uploadBoardBackground(snapshot.board.id, file, snapshot.revision);
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function saveSettings(event: FormEvent) {
    event.preventDefault();
    const cleaned = settingsName.trim();
    if (!canManage || !cleaned || cleaned === snapshot.board.name || busy) return;
    setBusy(true);
    setError("");
    try {
      await renameBoard(snapshot.board.id, cleaned, snapshot.revision);
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  async function archiveCommand(
    kind: "card" | "list",
    id: string,
    command: "restore" | "delete",
    displayName: string,
  ) {
    if (busy) return;
    if (command === "delete" && !window.confirm(`Permanently delete "${displayName}"? This cannot be undone.`)) {
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (kind === "card") {
        await commandArchivedCard(snapshot.board.id, id, command, snapshot.revision);
      } else {
        await commandArchivedList(snapshot.board.id, id, command, snapshot.revision);
      }
      await onChanged();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function titleForView() {
    if (view === "main") return "Menu";
    if (view === "visibility") return "Visibility";
    if (view === "settings") return "Settings";
    if (view === "background") return "Change background";
    if (view === "colors") return "Colors";
    if (view === "labels") return "Labels";
    if (view === "activity") return "Activity";
    return "Archived items";
  }

  const content = (
    <div
      className="trello-board-menu-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside className="trello-board-menu-panel" role="dialog" aria-modal="true" aria-label={titleForView()}>
        <Header
          title={titleForView()}
          canGoBack={view !== "main"}
          onBack={() => {
            setError("");
            setEditingLabel(undefined);
            setView(view === "colors" ? "background" : "main");
          }}
          onClose={onClose}
        />
        {error && <div className="trello-menu-error">{error}</div>}

        {view === "main" && (
          <div className="trello-board-menu__body trello-board-menu__main">
            <MenuRow
              icon="♙"
              label="Share"
              detail={`${snapshot.members.length} board member${snapshot.members.length === 1 ? "" : "s"}`}
              onClick={onOpenMembers}
            />
            <div className="trello-board-menu__divider" />
            <MenuRow
              icon="🔒"
              label="Visibility: Private"
              detail="Only board members can see this board"
              onClick={() => setView("visibility")}
            />
            <div className="trello-board-menu__divider" />
            <MenuRow
              icon={<TrelloMenuIcon kind="settings" />}
              label="Settings"
              onClick={() => setView("settings")}
            />
            <MenuRow
              icon={<TrelloMenuIcon kind="background" />}
              label="Change background"
              onClick={() => setView("background")}
            />
            <MenuRow
              icon={<TrelloMenuIcon kind="labels" />}
              label="Labels"
              onClick={() => setView("labels")}
            />
            <div className="trello-board-menu__divider" />
            <MenuRow
              icon={<TrelloMenuIcon kind="activity" />}
              label="Activity"
              onClick={() => setView("activity")}
            />
            <MenuRow
              icon={<TrelloMenuIcon kind="archive" />}
              label="Archived items"
              onClick={() => setView("archived")}
            />
          </div>
        )}

        {view === "visibility" && (
          <div className="trello-board-menu__body">
            <div className="trello-private-card">
              <span className="trello-private-card__icon">🔒</span>
              <div>
                <strong>Private board</strong>
                <p>Only users explicitly added to this board can see it or open its board URL.</p>
              </div>
            </div>
            <h4>Board members</h4>
            <div className="trello-menu-members">
              {snapshot.members.map((member) => (
                <div key={member.id}>
                  <span className="trello-member-avatar">{member.username.slice(0, 2).toUpperCase()}</span>
                  <span>
                    <strong>{member.username}</strong>
                    <small>{member.role === "MANAGER" ? "Board manager" : "Member"}</small>
                  </span>
                </div>
              ))}
            </div>
            {canManage && (
              <button className="button trello-primary-button trello-menu-wide-button" type="button" onClick={onOpenMembers}>
                Manage board members
              </button>
            )}
          </div>
        )}

        {view === "settings" && (
          <div className="trello-board-menu__body">
            <h4>Board settings</h4>
            <form className="trello-settings-form" onSubmit={saveSettings}>
              <label>
                Board name
                <input
                  value={settingsName}
                  maxLength={200}
                  disabled={!canManage || busy}
                  onChange={(event) => setSettingsName(event.target.value)}
                />
              </label>
              <button
                className="button trello-primary-button"
                disabled={!canManage || busy || !settingsName.trim() || settingsName.trim() === snapshot.board.name}
              >
                {busy ? "Saving…" : "Save board name"}
              </button>
            </form>
            <div className="trello-setting-summary">
              <span>🔒</span>
              <div>
                <strong>Private access</strong>
                <p>{snapshot.members.length} active board member{snapshot.members.length === 1 ? "" : "s"}.</p>
              </div>
            </div>
            {!canManage && (
              <p className="trello-menu-note">Only a board manager or administrator can change board settings.</p>
            )}
          </div>
        )}

        {view === "background" && (
          <div className="trello-board-menu__body">
            <input
              ref={fileRef}
              className="trello-hidden-file-input"
              type="file"
              accept="image/png,image/jpeg,image/webp"
              onChange={(event) => void uploadBackground(event)}
            />
            <div className="trello-background-choices">
              <button type="button" onClick={() => fileRef.current?.click()} disabled={busy}>
                <span
                  className="trello-background-choice__preview trello-background-choice__preview--photo"
                  style={
                    snapshot.board.background_image_url
                      ? { backgroundImage: `url("${snapshot.board.background_image_url}")` }
                      : undefined
                  }
                >
                  {!snapshot.board.background_image_url && "🖼️"}
                </span>
                <strong>Photos</strong>
              </button>
              <button type="button" onClick={() => setView("colors")}>
                <span className="trello-background-choice__preview trello-background-choice__preview--colors">
                  <i />
                  <i />
                </span>
                <strong>Colors</strong>
              </button>
            </div>
            <div className="trello-board-menu__divider" />
            <h4>Custom</h4>
            <button
              className="trello-custom-background"
              type="button"
              onClick={() => fileRef.current?.click()}
              disabled={busy}
              aria-label="Upload custom board background"
            >
              <span>＋</span>
            </button>
            <p className="trello-menu-note">
              PNG, JPEG, or WebP up to 10 MB. The uploaded background is private to this board.
            </p>
          </div>
        )}

        {view === "colors" && (
          <div className="trello-board-menu__body">
            <div className="trello-background-color-grid">
              {BACKGROUNDS.map((option) => (
                <button
                  key={option.key}
                  type="button"
                  className="trello-background-swatch"
                  style={{ background: option.gradient }}
                  aria-label={option.label}
                  aria-pressed={snapshot.board.background_key === option.key && !snapshot.board.background_image_url}
                  disabled={busy}
                  onClick={() => void chooseBackground(option.key)}
                >
                  <span>{option.emoji}</span>
                  {snapshot.board.background_key === option.key && !snapshot.board.background_image_url && (
                    <b aria-hidden="true">✓</b>
                  )}
                </button>
              ))}
            </div>
          </div>
        )}

        {view === "labels" && (
          <div className="trello-board-menu__body">
            {editingLabel !== undefined ? (
              <LabelEditor
                label={editingLabel}
                snapshot={snapshot}
                onCancel={() => setEditingLabel(undefined)}
                onSaved={async () => {
                  await onChanged();
                  setEditingLabel(undefined);
                }}
              />
            ) : (
              <>
                <input
                  className="trello-menu-search"
                  value={labelSearch}
                  placeholder="Search labels..."
                  aria-label="Search labels"
                  onChange={(event) => setLabelSearch(event.target.value)}
                />
                <h4>Labels</h4>
                <div className="trello-label-list">
                  {filteredLabels.map((label) => (
                    <div className="trello-label-row" key={label.id}>
                      <button
                        className="trello-label-bar"
                        data-label-color={label.color}
                        type="button"
                        title={label.description || label.name || `${label.color} label`}
                        onClick={() => setEditingLabel(label)}
                      >
                        <strong>{label.name}</strong>
                        {label.description && <small>{label.description}</small>}
                      </button>
                      <button
                        type="button"
                        aria-label={`Edit ${label.color} label`}
                        onClick={() => setEditingLabel(label)}
                      >
                        ✎
                      </button>
                    </div>
                  ))}
                </div>
                <button className="trello-create-label" type="button" onClick={() => setEditingLabel(null)}>
                  Create a new label
                </button>
                <p className="trello-menu-note">
                  Label names and descriptions explain what each color means. Team members can assign these labels from any card.
                </p>
              </>
            )}
          </div>
        )}

        {view === "activity" && (
          <div className="trello-board-menu__body trello-activity-view">
            <div className="trello-activity-tabs">
              <button type="button" aria-pressed={activityFilter === "all"} onClick={() => setActivityFilter("all")}>
                All
              </button>
              <button type="button" aria-pressed={activityFilter === "comment"} onClick={() => setActivityFilter("comment")}>
                Comments
              </button>
            </div>
            <p className="trello-menu-note">Showing board activity from the past 14 days.</p>
            {activityBusy ? (
              <div className="trello-menu-loading">Loading activity…</div>
            ) : filteredActivity.length === 0 ? (
              <div className="trello-menu-empty">No activity in this period.</div>
            ) : (
              <div className="trello-activity-list">
                {filteredActivity.map((row) => (
                  <article key={row.id}>
                    <span className="trello-activity-avatar">{row.actor_username.slice(0, 2).toUpperCase()}</span>
                    <div>
                      <p>{row.message}</p>
                      <time dateTime={row.created_at}>{formatDateTime(row.created_at)}</time>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        )}

        {view === "archived" && (
          <div className="trello-board-menu__body">
            <div className="trello-archive-controls">
              <input
                className="trello-menu-search"
                value={archiveSearch}
                placeholder="Search"
                aria-label="Search archived items"
                onChange={(event) => setArchiveSearch(event.target.value)}
              />
              <div className="trello-archive-tabs">
                <button type="button" aria-pressed={archiveTab === "cards"} onClick={() => setArchiveTab("cards")}>
                  Cards
                </button>
                <button type="button" aria-pressed={archiveTab === "lists"} onClick={() => setArchiveTab("lists")}>
                  Lists
                </button>
              </div>
            </div>
            <p className="trello-menu-note">Past 14 days</p>
            {archiveBusy ? (
              <div className="trello-menu-loading">Loading archived items…</div>
            ) : archiveTab === "cards" ? (
              <div className="trello-archive-list">
                {filteredCards.length === 0 && (
                  <div className="trello-menu-empty">No archived cards in the past 14 days.</div>
                )}
                {filteredCards.map((card) => (
                  <article key={card.id} className="trello-archive-item">
                    <div>
                      <strong>{card.title}</strong>
                      <small>▱ {card.column_name} · {card.archived_at ? formatDateTime(card.archived_at) : ""}</small>
                    </div>
                    <div className="trello-archive-item__actions">
                      <button type="button" disabled={busy} onClick={() => void archiveCommand("card", card.id, "restore", card.title)}>
                        Restore
                      </button>
                      <span>•</span>
                      <button type="button" disabled={busy} onClick={() => void archiveCommand("card", card.id, "delete", card.title)}>
                        Delete
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="trello-archive-list">
                {filteredLists.length === 0 && (
                  <div className="trello-menu-empty">No archived lists in the past 14 days.</div>
                )}
                {filteredLists.map((list) => (
                  <article key={list.id} className="trello-archive-item">
                    <div>
                      <strong>{list.name}</strong>
                      <small>
                        {list.card_count} card{list.card_count === 1 ? "" : "s"} · {list.archived_at ? formatDateTime(list.archived_at) : ""}
                      </small>
                    </div>
                    <div className="trello-archive-item__actions">
                      <button type="button" disabled={busy} onClick={() => void archiveCommand("list", list.id, "restore", list.name)}>
                        Restore
                      </button>
                      <span>•</span>
                      <button type="button" disabled={busy} onClick={() => void archiveCommand("list", list.id, "delete", list.name)}>
                        Delete
                      </button>
                    </div>
                  </article>
                ))}
              </div>
            )}
          </div>
        )}
      </aside>
    </div>
  );

  return createPortal(content, document.body);
}

export const BOARD_BACKGROUND_STYLES: Record<string, string> = Object.fromEntries(
  BACKGROUNDS.map((item) => [item.key, item.gradient]),
);
