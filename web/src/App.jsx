import { useEffect, useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import {
  MapContainer,
  TileLayer,
  Marker,
  Popup,
  useMap,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import L from "leaflet";
import "./App.css";

const API_URL =
  import.meta.env.VITE_API_URL ||
  (import.meta.env.PROD ? "/api" : "http://127.0.0.1:8000/api");

const busIcon = L.divIcon({
  className: "bus-marker",
  html: "<span>🚌</span>",
  iconSize: [42, 42],
  iconAnchor: [21, 21],
  popupAnchor: [0, -21],
});

function FitMapToVehicles({ vehicles }) {
  const map = useMap();

  useEffect(() => {
    if (!vehicles.length) return;

    const bounds = vehicles.map((vehicle) => [
      vehicle.latitude,
      vehicle.longitude,
    ]);

    if (bounds.length === 1) {
      map.setView(bounds[0], 15);
      return;
    }

    map.fitBounds(bounds, {
      padding: [55, 55],
      maxZoom: 15,
    });
  }, [vehicles, map]);

  return null;
}

function formatEta(minutes) {
  const totalSeconds = Math.max(1, Math.round(Number(minutes || 0) * 60));

  if (totalSeconds < 60) {
    return `${totalSeconds} s`;
  }

  const mins = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;

  return seconds ? `${mins} min ${seconds} s` : `${mins} min`;
}

function App() {
  const [routes, setRoutes] = useState([]);
  const [selectedRoute, setSelectedRoute] = useState("");
  const [vehicles, setVehicles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [hasSearched, setHasSearched] = useState(false);

  const [chatMessage, setChatMessage] = useState("");
  const [chatAnswer, setChatAnswer] = useState("");
  const [chatLoading, setChatLoading] = useState(false);
  const [chatError, setChatError] = useState("");

  useEffect(() => {
    async function loadRoutes() {
      try {
        const response = await fetch(`${API_URL}/routes`);

        if (!response.ok) {
          throw new Error("No fue posible cargar las rutas.");
        }

        const data = await response.json();
        setRoutes(data);
      } catch (err) {
        setError(err.message);
      }
    }

    loadRoutes();
  }, []);

  const sortedVehicles = useMemo(
    () =>
      [...vehicles].sort(
        (a, b) => Number(a.eta_minutes) - Number(b.eta_minutes)
      ),
    [vehicles]
  );

  const selectedRouteInfo = useMemo(
    () => routes.find((route) => route.route_id === selectedRoute),
    [routes, selectedRoute]
  );

  async function loadVehicles() {
    if (!selectedRoute) {
      setError("Selecciona una ruta primero.");
      return;
    }

    setLoading(true);
    setError("");
    setHasSearched(false);
    setVehicles([]);
    setChatAnswer("");
    setChatError("");

    try {
      const response = await fetch(
        `${API_URL}/live?route_id=${encodeURIComponent(selectedRoute)}&limit=20`
      );

      if (!response.ok) {
        throw new Error(
          "No fue posible consultar los datos en tiempo real."
        );
      }

      const data = await response.json();
      setVehicles(data.vehicles || []);
      setHasSearched(true);
    } catch (err) {
      setError(err.message);
      setVehicles([]);
      setHasSearched(false);
    } finally {
      setLoading(false);
    }
  }

  async function askAssistant() {
    if (!chatMessage.trim()) {
      setChatError("Escribe una pregunta primero.");
      return;
    }

    if (!selectedRoute) {
      setChatError(
        "Selecciona una ruta antes de consultar al asistente."
      );
      return;
    }

    setChatLoading(true);
    setChatError("");
    setChatAnswer("");

    try {
      const response = await fetch(`${API_URL}/chat`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          message: chatMessage,
          route_id: selectedRoute,
        }),
      });

      if (!response.ok) {
        throw new Error("No fue posible consultar al asistente.");
      }

      const data = await response.json();
      setChatAnswer(data.answer);
      setChatMessage("");
    } catch (err) {
      setChatError(err.message);
    } finally {
      setChatLoading(false);
    }
  }

  return (
    <div className="app">
      <header className="hero">
        <div className="hero-inner">
          <div className="hero-copy">
            <div className="brand-row">
              <span className="brand-icon">M</span>
              <p className="eyebrow hero-eyebrow">
                MOVILIDAD INTELIGENTE · CDMX
              </p>
            </div>

            <h1>
              Tu Metrobús,
              <span> un poco más predecible.</span>
            </h1>

            <p className="subtitle">
              Consulta unidades en tiempo real y estima su llegada a la
              próxima parada con GTFS-Realtime y Machine Learning.
            </p>

            <div className="hero-tags">
              <span>GTFS-Realtime</span>
              <span>Machine Learning</span>
              <span>OpenAI</span>
            </div>
          </div>

          <div className="status">
            <span className="status-dot"></span>
            <div>
              <small>ESTADO</small>
              <strong>Sistema activo</strong>
            </div>
          </div>
        </div>
      </header>

      <main>
        <section className="search-panel">
          <div className="search-copy">
            <span className="search-icon">⌕</span>
            <div>
              <span className="panel-kicker">CONSULTA EN TIEMPO REAL</span>
              <h2>¿Qué ruta quieres consultar?</h2>
            </div>
          </div>

          <div className="search-controls">
            <div className="field">
              <label htmlFor="route">Ruta de Metrobús</label>
              <select
                id="route"
                value={selectedRoute}
                onChange={(event) => {
                  setSelectedRoute(event.target.value);
                  setVehicles([]);
                  setHasSearched(false);
                  setError("");
                  setChatAnswer("");
                  setChatError("");
                  setChatMessage("");
                }}
              >
                <option value="">Selecciona una ruta de Metrobús</option>

                {routes.map((route) => (
                  <option key={route.route_id} value={route.route_id}>
                    {route.route_long_name ||
                      route.route_short_name ||
                      route.route_id}
                  </option>
                ))}
              </select>
            </div>

            <button
              className="primary-button"
              onClick={loadVehicles}
              disabled={loading || !selectedRoute}
            >
              {loading ? "Consultando..." : "Buscar unidades"}
              <span aria-hidden="true">→</span>
            </button>
          </div>
        </section>

        {error && <div className="error-message">{error}</div>}

        <section className="summary">
          <article className="summary-card">
            <div className="summary-icon">⌘</div>
            <div>
              <span>Rutas disponibles</span>
              <strong>{routes.length}</strong>
            </div>
          </article>

          <article className="summary-card">
            <div className="summary-icon">🚌</div>
            <div>
              <span>Unidades encontradas</span>
              <strong>{vehicles.length}</strong>
            </div>
          </article>

          <article className="summary-card">
            <div className="summary-icon live">●</div>
            <div>
              <span>Fuente de posición</span>
              <strong>GTFS-RT</strong>
            </div>
          </article>

          <article className="summary-card">
            <div className="summary-icon">✦</div>
            <div>
              <span>Motor de predicción</span>
              <strong>ML ETA</strong>
            </div>
          </article>
        </section>

        {vehicles.length > 0 && (
          <section className="live-dashboard">
            <div className="map-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">MAPA EN VIVO</p>
                  <h2>Unidades de la ruta</h2>
                  <p>
                    {selectedRouteInfo?.route_long_name ||
                      selectedRouteInfo?.route_short_name ||
                      `Ruta ${selectedRoute}`}
                  </p>
                </div>
                <span className="live-pill">
                  <span></span> Actualizado
                </span>
              </div>

              <div className="map-wrapper">
                <MapContainer
                  center={[19.4326, -99.1332]}
                  zoom={11}
                  scrollWheelZoom={true}
                  className="map"
                >
                  <TileLayer
                    attribution="&copy; OpenStreetMap contributors"
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />

                  <FitMapToVehicles vehicles={vehicles} />

                  {vehicles.map((vehicle, index) => (
                    <Marker
                      key={`map-${vehicle.route_id}-${index}`}
                      position={[vehicle.latitude, vehicle.longitude]}
                      icon={busIcon}
                    >
                      <Popup>
                        <div className="map-popup">
                          <span className="popup-label">PRÓXIMA PARADA</span>
                          <strong>{vehicle.next_stop_name}</strong>
                          <div className="popup-eta">
                            {formatEta(vehicle.eta_minutes)}
                          </div>
                          <div className="popup-meta">
                            <span>
                              {Math.round(
                                vehicle.distance_to_next_stop_m
                              )}{" "}
                              m de distancia
                            </span>
                            <span>{vehicle.progress_pct.toFixed(1)}% avance</span>
                          </div>
                        </div>
                      </Popup>
                    </Marker>
                  ))}
                </MapContainer>
              </div>
            </div>

            <aside className="arrival-panel">
              <div className="panel-heading compact">
                <div>
                  <p className="eyebrow">PRÓXIMAS UNIDADES</p>
                  <h2>¿Cuál llega primero?</h2>
                </div>
                <span className="result-count">
                  {sortedVehicles.length} en vivo
                </span>
              </div>

              <div className="arrival-list">
                {sortedVehicles.map((vehicle, index) => (
                  <article
                    className={`arrival-card ${
                      index === 0 ? "arrival-card-first" : ""
                    }`}
                    key={`arrival-${vehicle.route_id}-${index}`}
                  >
                    <div className="arrival-number">
                      {String(index + 1).padStart(2, "0")}
                    </div>

                    <div className="arrival-content">
                      <div className="arrival-top">
                        <div>
                          <span className="arrival-label">
                            {index === 0 ? "LLEGA PRIMERO" : "PRÓXIMA PARADA"}
                          </span>
                          <h3>{vehicle.next_stop_name}</h3>
                        </div>
                        <strong className="arrival-eta">
                          {formatEta(vehicle.eta_minutes)}
                        </strong>
                      </div>

                      <div className="progress-track">
                        <span
                          style={{
                            width: `${Math.min(
                              100,
                              Math.max(0, vehicle.progress_pct)
                            )}%`,
                          }}
                        ></span>
                      </div>

                      <div className="arrival-meta">
                        <span>
                          {Math.round(vehicle.distance_to_next_stop_m)} m
                        </span>
                        <span>{vehicle.progress_pct.toFixed(1)}% de avance</span>
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </aside>
          </section>
        )}

        <section className="results">
          <div className="section-heading">
            <div>
              <p className="eyebrow">MONITOREO</p>
              <h2>Detalle de unidades</h2>
              <p className="section-description">
                Predicciones del modelo para la próxima parada de cada unidad.
              </p>
            </div>

            {vehicles.length > 0 && (
              <span className="result-count">
                {vehicles.length} unidades
              </span>
            )}
          </div>

          {loading ? (
            <div className="empty-state">
              <div className="empty-icon loading-icon">↻</div>
              <h3>Consultando unidades...</h3>
              <p>
                Obteniendo GTFS-Realtime y calculando estimaciones de llegada.
              </p>
            </div>
          ) : vehicles.length === 0 ? (
            <div className="empty-state">
              <div className="empty-icon">🚌</div>

              {hasSearched ? (
                <>
                  <h3>Sin unidades disponibles en este momento</h3>
                  <p>
                    No encontramos observaciones GTFS-Realtime válidas para
                    esta ruta. Intenta nuevamente en unos momentos.
                  </p>
                </>
              ) : (
                <>
                  <h3>Elige una ruta para comenzar</h3>
                  <p>
                    Consulta unidades disponibles, su próxima parada y el ETA
                    estimado por el modelo.
                  </p>
                </>
              )}
            </div>
          ) : (
            <div className="vehicle-grid">
              {sortedVehicles.map((vehicle, index) => (
                <article
                  className="vehicle-card"
                  key={`${vehicle.route_id}-${index}`}
                >
                  <div className="card-top">
                    <span className="route-badge">
                      Ruta {vehicle.route_id}
                    </span>
                    <span className="live-badge">
                      <span></span> EN VIVO
                    </span>
                  </div>

                  <div className="vehicle-main">
                    <p className="next-stop">PRÓXIMA PARADA</p>
                    <h3>{vehicle.next_stop_name}</h3>
                    <div className="eta">
                      <strong>{formatEta(vehicle.eta_minutes)}</strong>
                    </div>
                  </div>

                  <div className="progress-block">
                    <div className="progress-copy">
                      <span>Avance estimado</span>
                      <strong>{vehicle.progress_pct.toFixed(1)}%</strong>
                    </div>
                    <div className="progress-track">
                      <span
                        style={{
                          width: `${Math.min(
                            100,
                            Math.max(0, vehicle.progress_pct)
                          )}%`,
                        }}
                      ></span>
                    </div>
                  </div>

                  <div className="card-details">
                    <div>
                      <span>Distancia</span>
                      <strong>
                        {Math.round(vehicle.distance_to_next_stop_m)} m
                      </strong>
                    </div>
                    <div>
                      <span>ETA</span>
                      <strong>{formatEta(vehicle.eta_minutes)}</strong>
                    </div>
                  </div>

                  <p className="route-name">{vehicle.route_name}</p>
                </article>
              ))}
            </div>
          )}
        </section>

        <section className="method-section">
          <div className="method-copy">
            <p className="eyebrow">CIENCIA DE DATOS</p>
            <h2>¿Cómo calculamos el ETA?</h2>
            <p>
              El sistema combina información estática y posiciones en tiempo
              real para localizar cada unidad sobre su ruta, identificar la
              próxima parada y alimentar el modelo de Machine Learning.
            </p>

            <div className="pipeline">
              <div className="pipeline-step">
                <span>01</span>
                <strong>GTFS</strong>
                <small>Rutas y paradas</small>
              </div>
              <div className="pipeline-arrow">→</div>
              <div className="pipeline-step">
                <span>02</span>
                <strong>GTFS-RT</strong>
                <small>Posición actual</small>
              </div>
              <div className="pipeline-arrow">→</div>
              <div className="pipeline-step">
                <span>03</span>
                <strong>Map Matching</strong>
                <small>Unidad sobre ruta</small>
              </div>
              <div className="pipeline-arrow">→</div>
              <div className="pipeline-step">
                <span>04</span>
                <strong>Modelo ML</strong>
                <small>Predicción ETA</small>
              </div>
            </div>
          </div>

          <div className="model-card">
            <div className="model-card-top">
              <div>
                <span className="model-label">MODELO ETA</span>
                <h3>HistGradientBoosting</h3>
              </div>
              <span className="model-status">ML</span>
            </div>

            <div className="model-metrics">
              <div>
                <span>MAE temporal</span>
                <strong>0.503</strong>
                <small>minutos</small>
              </div>
              <div>
                <span>R²</span>
                <strong>0.661</strong>
                <small>test temporal</small>
              </div>
              <div>
                <span>Mejora</span>
                <strong>24.5%</strong>
                <small>vs. baseline</small>
              </div>
            </div>

            <p className="model-note">
              Métricas obtenidas sobre el conjunto de prueba temporal de los
              datos recolectados. No representan una garantía universal de
              precisión.
            </p>
          </div>
        </section>

        <section className="chat-section">
          <div className="chat-shell">
            <div className="chat-copy">
              <div className="assistant-icon">✦</div>
              <p className="eyebrow">ASISTENTE IA</p>
              <h2>Pregunta por tu ruta.</h2>
              <p>
                El asistente interpreta únicamente la información validada por
                el sistema. El ETA sigue siendo generado por nuestro modelo de
                Machine Learning.
              </p>

              <div className="suggested-questions">
                <button
                  type="button"
                  onClick={() =>
                    setChatMessage("¿Cuánto falta para que lleguen?")
                  }
                >
                  ¿Cuánto falta para que lleguen?
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setChatMessage("¿Cuál unidad llega primero?")
                  }
                >
                  ¿Cuál llega primero?
                </button>
              </div>
            </div>

            <div className="chat-card">
              <div className="chat-card-header">
                <div>
                  <span className="ai-badge">OpenAI</span>
                  <strong>Asistente CDMX Bus ETA</strong>
                </div>
                <span className="chat-online">● En línea</span>
              </div>

              {selectedRoute ? (
                <div className="chat-route-context">
                  Contexto activo: <strong>Ruta {selectedRoute}</strong>
                </div>
              ) : (
                <div className="chat-route-context warning">
                  Selecciona una ruta para consultar información en tiempo real.
                </div>
              )}

              <div className="chat-input-row">
                <input
                  type="text"
                  value={chatMessage}
                  onChange={(event) => setChatMessage(event.target.value)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" && !chatLoading) {
                      askAssistant();
                    }
                  }}
                  placeholder="Ej. ¿Cuánto falta para las próximas unidades?"
                />

                <button
                  onClick={askAssistant}
                  disabled={
                    chatLoading ||
                    !chatMessage.trim() ||
                    !selectedRoute
                  }
                >
                  {chatLoading ? "Consultando..." : "Preguntar"}
                </button>
              </div>

              {chatError && <div className="chat-error">{chatError}</div>}

              {chatAnswer && (
                <div className="chat-answer">
                  <div className="assistant-icon small">✦</div>
                  <div>
                    <strong>Respuesta del asistente</strong>
                    <div className="chat-markdown">
                      <ReactMarkdown>{chatAnswer}</ReactMarkdown>
                    </div>
                    <span className="chat-disclaimer">
                      Los tiempos son estimaciones generadas por el modelo ML
                      del proyecto.
                    </span>
                  </div>
                </div>
              )}
            </div>
          </div>
        </section>

        <footer className="footer">
          <div>
            <strong>CDMX Bus ETA</strong>
            <span>Proyecto de Ciencia de Datos · Metrobús CDMX</span>
          </div>
          <span>GTFS · GTFS-Realtime · Machine Learning · OpenAI</span>
        </footer>
      </main>
    </div>
  );
}

export default App;
