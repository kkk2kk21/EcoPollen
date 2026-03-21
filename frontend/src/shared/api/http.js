export const DEFAULT_REQUEST_TIMEOUT_MS = 60 * 1000;

function timeoutMessage(timeoutMs) {
  const seconds = Math.max(1, Math.round(Number(timeoutMs || DEFAULT_REQUEST_TIMEOUT_MS) / 1000));
  return `Запрос выполнялся дольше ${seconds} сек. Попробуйте ещё раз`;
}

function parseResponseText(text) {
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export async function fetchWithTimeout(url, options = {}) {
  const { timeoutMs = DEFAULT_REQUEST_TIMEOUT_MS, signal, ...fetchOptions } = options;

  if (!timeoutMs || timeoutMs <= 0) {
    return fetch(url, { ...fetchOptions, signal });
  }

  const controller = new AbortController();
  let timedOut = false;

  const abortFromParent = () => {
    controller.abort(signal?.reason);
  };

  if (signal) {
    if (signal.aborted) {
      controller.abort(signal.reason);
    } else {
      signal.addEventListener("abort", abortFromParent, { once: true });
    }
  }

  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort(new DOMException("Request timeout", "AbortError"));
  }, timeoutMs);

  try {
    return await fetch(url, { ...fetchOptions, signal: controller.signal });
  } catch (error) {
    if (timedOut) {
      throw new Error(timeoutMessage(timeoutMs));
    }
    throw error;
  } finally {
    window.clearTimeout(timer);
    if (signal) {
      signal.removeEventListener("abort", abortFromParent);
    }
  }
}

export async function requestJson(url, options = {}) {
  const { errorMessage = "Не удалось загрузить данные", ...fetchOptions } = options;
  const response = await fetchWithTimeout(url, fetchOptions);
  const text = await response.text();
  const data = parseResponseText(text);

  if (!response.ok) {
    const detail =
      typeof data === "string"
        ? data
        : data?.detail || data?.message || errorMessage;
    throw new Error(`HTTP ${response.status}: ${detail}`);
  }

  return data;
}
