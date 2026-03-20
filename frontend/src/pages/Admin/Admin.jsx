import { useEffect, useMemo, useState } from "react";
import { apiFetch, clearToken, getToken } from "../../shared/api/auth";
import "./Admin.css";

const ROLE_OPTIONS = [
  { value: "student", label: "student" },
  { value: "scientist", label: "scientist" },
  { value: "admin", label: "admin" },
];

function formatDateTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("ru-RU", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function makeEmptyCreateForm() {
  return {
    email: "",
    password: "",
    role: "student",
  };
}

export default function Admin() {
  const [me, setMe] = useState(null);
  const [meErr, setMeErr] = useState("");
  const [users, setUsers] = useState([]);
  const [usersErr, setUsersErr] = useState("");
  const [userSearch, setUserSearch] = useState("");
  const [roleFilter, setRoleFilter] = useState("all");
  const [createForm, setCreateForm] = useState(makeEmptyCreateForm);
  const [createStatus, setCreateStatus] = useState("");
  const [userDrafts, setUserDrafts] = useState({});
  const [userStatuses, setUserStatuses] = useState({});

  const canManage = useMemo(() => me?.role === "admin", [me]);
  const filteredUsers = useMemo(() => {
    const normalizedSearch = userSearch.trim().toLowerCase();

    return users.filter((user) => {
      const matchesRole = roleFilter === "all" || user.role === roleFilter;
      const matchesSearch =
        !normalizedSearch || String(user.email || "").toLowerCase().includes(normalizedSearch);
      return matchesRole && matchesSearch;
    });
  }, [roleFilter, userSearch, users]);

  function setUserStatus(userId, message) {
    setUserStatuses((prev) => ({ ...prev, [userId]: message }));
  }

  function syncUserDrafts(items) {
    setUserDrafts((prev) =>
      Object.fromEntries(
        (Array.isArray(items) ? items : []).map((user) => [
          user.id,
          {
            email: prev[user.id]?.email || user.email,
            role: prev[user.id]?.role || user.role,
            password: "",
          },
        ])
      )
    );
  }

  async function loadUsers() {
    setUsersErr("");
    try {
      const items = await apiFetch("/api/v1/admin/users");
      const nextUsers = Array.isArray(items) ? items : [];
      setUsers(nextUsers);
      syncUserDrafts(nextUsers);
    } catch (e) {
      setUsersErr(String(e));
    }
  }

  useEffect(() => {
    if (!getToken()) {
      setMeErr("Нужно войти в систему под администратором.");
      return;
    }

    apiFetch("/api/v1/auth/me")
      .then((payload) => setMe(payload))
      .catch((e) => setMeErr(String(e)));
  }, []);

  useEffect(() => {
    if (!canManage) return;
    loadUsers();
  }, [canManage]);

  function onLogout() {
    clearToken();
    location.href = "/login";
  }

  async function onCreateUser(e) {
    e.preventDefault();
    setCreateStatus("Создаю пользователя...");

    try {
      await apiFetch("/api/v1/admin/users", {
        method: "POST",
        body: JSON.stringify({
          email: createForm.email.trim(),
          password: createForm.password,
          role: createForm.role,
        }),
      });
      setCreateForm(makeEmptyCreateForm());
      setCreateStatus("Пользователь создан.");
      await loadUsers();
    } catch (e2) {
      setCreateStatus(String(e2));
    }
  }

  async function onSaveUser(user) {
    const draft = userDrafts[user.id] || { email: user.email, role: user.role, password: "" };
    const payload = {};

    if (draft.email.trim().toLowerCase() !== String(user.email || "").toLowerCase()) {
      payload.email = draft.email.trim();
    }
    if (draft.role !== user.role) {
      payload.role = draft.role;
    }
    if (draft.password.trim()) {
      payload.password = draft.password.trim();
    }

    if (!Object.keys(payload).length) {
      setUserStatus(user.id, "Нет изменений для сохранения.");
      return;
    }

    setUserStatus(user.id, "Сохраняю...");
    try {
      const updated = await apiFetch(`/api/v1/admin/users/${user.id}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });

      setUsers((prev) =>
        prev.map((item) => (item.id === user.id ? updated : item))
      );
      if (me?.id === user.id) {
        setMe(updated);
      }
      setUserDrafts((prev) => ({
        ...prev,
        [user.id]: {
          email: updated.email,
          role: updated.role,
          password: "",
        },
      }));
      setUserStatus(user.id, "Изменения сохранены.");
    } catch (e) {
      setUserStatus(user.id, String(e));
    }
  }

  async function onDeleteUser(user) {
    const confirmation = prompt(
      `Чтобы удалить пользователя «${user.email}», введите ПОДТВЕРЖДАЮ`
    );
    if (confirmation == null) return;
    if (confirmation.trim() !== "ПОДТВЕРЖДАЮ") {
      setUserStatus(user.id, "Удаление отменено: кодовое слово введено неверно.");
      return;
    }

    setUserStatus(user.id, "Удаляю пользователя...");
    try {
      await apiFetch(`/api/v1/admin/users/${user.id}`, {
        method: "DELETE",
      });
      setUsers((prev) => prev.filter((item) => item.id !== user.id));
      setUserDrafts((prev) => {
        const next = { ...prev };
        delete next[user.id];
        return next;
      });
    } catch (e) {
      setUserStatus(user.id, String(e));
    }
  }

  return (
    <div className="grid admin-page" style={{ gap: 14 }}>
      <div className="row" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>Админ-панель</h2>
        <button onClick={onLogout}>Выйти</button>
      </div>

      {meErr ? <div className="note">{meErr}</div> : null}

      {me ? (
        <div className="card">
          <div className="admin-user-meta">
            <span>
              Вы вошли как: <b>{me.email}</b>
            </span>
            <span>
              • роль: <b>{me.role}</b>
            </span>
          </div>
        </div>
      ) : null}

      {me && !canManage ? (
        <div className="note">
          Эта панель доступна только администратору.
        </div>
      ) : null}

      {canManage ? (
        <div className="admin-layout">
          <div className="card">
            <div className="admin-section-head">
              <h3 className="admin-section-title">Новый пользователь</h3>
              <p className="admin-section-copy">
                Здесь можно создать пользователя и сразу назначить ему роль.
              </p>
            </div>

            <form className="grid admin-form" onSubmit={onCreateUser}>
              <label className="admin-field">
                <span>Email</span>
                <input
                  value={createForm.email}
                  onChange={(e) =>
                    setCreateForm((prev) => ({ ...prev, email: e.target.value }))
                  }
                  placeholder="user@example.com"
                />
              </label>

              <label className="admin-field">
                <span>Пароль</span>
                <input
                  type="password"
                  value={createForm.password}
                  onChange={(e) =>
                    setCreateForm((prev) => ({ ...prev, password: e.target.value }))
                  }
                  placeholder="Не короче 6 символов"
                />
              </label>

              <label className="admin-field">
                <span>Роль</span>
                <select
                  value={createForm.role}
                  onChange={(e) =>
                    setCreateForm((prev) => ({ ...prev, role: e.target.value }))
                  }
                >
                  {ROLE_OPTIONS.map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </label>

              <button type="submit">Создать пользователя</button>
            </form>

            {createStatus ? <div className="note note-muted">{createStatus}</div> : null}
          </div>

          <div className="card admin-users-card">
            <div className="admin-section-head">
              <h3 className="admin-section-title">Пользователи</h3>
              <p className="admin-section-copy">
                Меняйте роли, задавайте новые пароли и при необходимости удаляйте пользователей.
              </p>
            </div>

            {usersErr ? <div className="note">{usersErr}</div> : null}

            <div className="admin-users-filters">
              <label className="admin-field">
                <span>Поиск по логину</span>
                <input
                  value={userSearch}
                  onChange={(e) => setUserSearch(e.target.value)}
                  placeholder="Например, admin@ecopollen.local"
                />
              </label>

              <label className="admin-field">
                <span>Тип пользователя</span>
                <select value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
                  <option value="all">Все</option>
                  {ROLE_OPTIONS.map((role) => (
                    <option key={role.value} value={role.value}>
                      {role.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <div className="admin-users-list">
              {filteredUsers.map((user) => {
                const draft = userDrafts[user.id] || {
                  email: user.email,
                  role: user.role,
                  password: "",
                };
                const isCurrentUser = me?.id === user.id;

                return (
                  <div key={user.id} className="admin-user-card">
                    <div className="admin-user-card-head">
                      <div className="admin-user-card-title">
                        <b>{user.email}</b>
                        <div className="admin-user-card-subtitle">
                          Создан: {formatDateTime(user.created_at)}
                        </div>
                      </div>
                      <div className="row">
                        {isCurrentUser ? <span className="badge">Это вы</span> : null}
                        <span className="badge badge-neutral">{user.role}</span>
                      </div>
                    </div>

                    <div className="admin-user-grid">
                      <label className="admin-field admin-user-grid-span">
                        <span>Логин</span>
                        <input
                          value={draft.email}
                          onChange={(e) =>
                            setUserDrafts((prev) => ({
                              ...prev,
                              [user.id]: {
                                ...draft,
                                email: e.target.value,
                              },
                            }))
                          }
                          placeholder="user@example.com"
                        />
                      </label>

                      <label className="admin-field">
                        <span>Роль</span>
                        <select
                          value={draft.role}
                          onChange={(e) =>
                            setUserDrafts((prev) => ({
                              ...prev,
                              [user.id]: {
                                ...draft,
                                role: e.target.value,
                              },
                            }))
                          }
                        >
                          {ROLE_OPTIONS.map((role) => (
                            <option key={role.value} value={role.value}>
                              {role.label}
                            </option>
                          ))}
                        </select>
                      </label>

                      <label className="admin-field">
                        <span>Новый пароль</span>
                        <input
                          type="password"
                          value={draft.password}
                          onChange={(e) =>
                            setUserDrafts((prev) => ({
                              ...prev,
                              [user.id]: {
                                ...draft,
                                password: e.target.value,
                              },
                            }))
                          }
                          placeholder="Оставьте пустым, если менять не нужно"
                        />
                      </label>
                    </div>

                    <div className="row admin-user-actions">
                      <button type="button" onClick={() => onSaveUser(user)}>
                        Сохранить
                      </button>
                      <button
                        type="button"
                        className="admin-danger-button"
                        onClick={() => onDeleteUser(user)}
                        disabled={isCurrentUser}
                      >
                        Удалить
                      </button>
                    </div>

                    {userStatuses[user.id] ? (
                      <div className="note note-muted">{userStatuses[user.id]}</div>
                    ) : null}
                  </div>
                );
              })}

              {!filteredUsers.length ? (
                <div className="note note-muted">
                  По текущему фильтру пользователей не найдено.
                </div>
              ) : null}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}
