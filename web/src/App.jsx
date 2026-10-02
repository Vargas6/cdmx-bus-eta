import { useEffect, useState } from "react";
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
  import.meta.env.VITE_API_URL || "http://127.0.0.1:8000";
  

// ==================================================
// ICONO DE AUTOBÚS
// ==================================================

const busIcon = L.divIcon({
  className: "bus-marker",
  html: "🚌",
  iconSize: [36, 36],
  iconAnchor: [18, 18],
  popupAnchor: [0, -18],
});

// ==================================================
// AJUSTAR MAPA A LAS UNIDADES
// ==================================================

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
      padding: [50, 50],
      maxZoom: 15,
    });
  }, [vehicles, map]);

  return null;
}

// ==================================================
// APLICACIÓN
// ==================================================

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

  // ==================================================
  // CARGAR RUTAS
  // ==================================================

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

  // ==================================================
  // CONSULTAR VEHÍCULOS EN TIEMPO REAL
  // ==================================================

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
        `${API_URL}/live?route_id=${encodeURIComponent(
          selectedRoute
        )}&limit=20`
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

  // ==================================================
  // CONSULTAR ASISTENTE OPENAI
  // ==================================================

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
        throw new Error(
          "No fue posible consultar al asistente."
        );
      }

      const data = await response.json();

      setChatAnswer(data.answer);

      // Limpiar la pregunta después de una respuesta exitosa.
      setChatMessage("");
    } catch (err) {
      setChatError(err.message);
    } finally {
      setChatLoading(false);
    }
  }

  // ==================================================
  // INTERFAZ
  // ==================================================

  return (
    <div className="app">

      {/* ENCABEZADO */}

      <header className="hero">
        <div>
          <p className="eyebrow">
            METROBÚS CDMX · DATOS EN TIEMPO REAL
          </p>

          <h1>CDMX Bus ETA</h1>

          <p className="subtitle">
            Estimación de llegada a la próxima parada mediante
            GTFS-Realtime y Machine Learning.
          </p>
        </div>

        <div className="status">
          <span className="status-dot"></span>
          Sistema activo
        </div>
      </header>

      <main>

        {/* SELECTOR DE RUTA */}

        <section className="search-panel">

          <div className="field">
            <label htmlFor="route">
              Selecciona una ruta
            </label>

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
              <option value="">
                Selecciona una ruta de Metrobús
              </option>

              {routes.map((route) => (
                <option
                  key={route.route_id}
                  value={route.route_id}
                >
                  {route.route_long_name ||
                    route.route_short_name ||
                    route.route_id}
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={loadVehicles}
            disabled={loading || !selectedRoute}
          >
            {loading
              ? "Consultando..."
              : "Consultar unidades"}
          </button>

        </section>

        {/* ERRORES */}

        {error && (
          <div className="error-message">
            {error}
          </div>
        )}

        {/* RESUMEN */}

        <section className="summary">

          <div>
            <span>Rutas disponibles</span>
            <strong>{routes.length}</strong>
          </div>

          <div>
            <span>Unidades encontradas</span>
            <strong>{vehicles.length}</strong>
          </div>

          <div>
            <span>Fuente</span>
            <strong>GTFS-RT</strong>
          </div>

          <div>
            <span>Modelo</span>
            <strong>ML ETA</strong>
          </div>

        </section>

        {/* MAPA */}

        {vehicles.length > 0 && (
          <section className="map-section">

            <div className="section-heading">

              <div>
                <p className="eyebrow">
                  UBICACIÓN
                </p>

                <h2>
                  Unidades sobre el mapa
                </h2>
              </div>

              <span className="result-count">
                Datos GTFS-Realtime
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

                <FitMapToVehicles
                  vehicles={vehicles}
                />

                {vehicles.map((vehicle, index) => (
                  <Marker
                    key={`map-${vehicle.route_id}-${index}`}
                    position={[
                      vehicle.latitude,
                      vehicle.longitude,
                    ]}
                    icon={busIcon}
                  >

                    <Popup>
                      <div className="map-popup">

                        <strong>
                          {vehicle.next_stop_name}
                        </strong>

                        <span>
                          Próxima parada
                        </span>

                        <hr />

                        <b>
                          ETA:{" "}
                          {vehicle.eta_minutes < 1
                            ? "< 1 min"
                            : `${vehicle.eta_minutes.toFixed(
                                1
                              )} min`}
                        </b>

                        <span>
                          Distancia:{" "}
                          {Math.round(
                            vehicle.distance_to_next_stop_m
                          )}{" "}
                          m
                        </span>

                        <span>
                          Ruta: {vehicle.route_name}
                        </span>

                      </div>
                    </Popup>

                  </Marker>
                ))}

              </MapContainer>

            </div>

          </section>
        )}

        {/* UNIDADES EN TIEMPO REAL */}

        <section className="results">

          <div className="section-heading">

            <div>
              <p className="eyebrow">
                MONITOREO
              </p>

              <h2>
                Unidades en tiempo real
              </h2>
            </div>

            {vehicles.length > 0 && (
              <span className="result-count">
                {vehicles.length} unidades
              </span>
            )}

          </div>

          {loading ? (

            <div className="empty-state">

              <h3>
                Consultando unidades...
              </h3>

              <p>
                Obteniendo información de GTFS-Realtime
                y calculando estimaciones de llegada.
              </p>

            </div>

          ) : vehicles.length === 0 ? (

            <div className="empty-state">

              {hasSearched ? (
                <>
                  <h3>
                    Sin unidades disponibles en este momento
                  </h3>

                  <p>
                    No se encontraron observaciones
                    GTFS-Realtime válidas para esta ruta
                    en la consulta actual. Intenta nuevamente
                    en unos momentos o selecciona otra ruta.
                  </p>
                </>
              ) : (
                <>
                  <h3>
                    Selecciona una ruta
                  </h3>

                  <p>
                    Consulta las unidades disponibles
                    para visualizar su próxima parada
                    y ETA estimado.
                  </p>
                </>
              )}

            </div>

          ) : (

            <div className="vehicle-grid">

              {vehicles.map((vehicle, index) => (

                <article
                  className="vehicle-card"
                  key={`${vehicle.route_id}-${index}`}
                >

                  <div className="card-top">

                    <span className="route-badge">
                      Ruta {vehicle.route_id}
                    </span>

                    <span className="live-badge">
                      EN VIVO
                    </span>

                  </div>

                  <h3>
                    {vehicle.next_stop_name}
                  </h3>

                  <p className="next-stop">
                    Próxima parada
                  </p>

                  <div className="eta">

                    {vehicle.eta_minutes < 1 ? (
                      <>
                        <strong>&lt; 1</strong>
                        <span>min</span>
                      </>
                    ) : (
                      <>
                        <strong>
                          {vehicle.eta_minutes.toFixed(1)}
                        </strong>
                        <span>min</span>
                      </>
                    )}

                  </div>

                  <div className="card-details">

                    <div>
                      <span>Distancia</span>

                      <strong>
                        {Math.round(
                          vehicle.distance_to_next_stop_m
                        )}{" "}
                        m
                      </strong>
                    </div>

                    <div>
                      <span>Avance</span>

                      <strong>
                        {vehicle.progress_pct.toFixed(1)}%
                      </strong>
                    </div>

                  </div>

                  <p className="route-name">
                    {vehicle.route_name}
                  </p>

                </article>
              ))}

            </div>

          )}

        </section>

        {/* ASISTENTE OPENAI */}

        <section className="chat-section">

          <div className="section-heading">

            <div>
              <p className="eyebrow">
                ASISTENTE IA
              </p>

              <h2>
                Pregunta sobre tu ruta
              </h2>
            </div>

            <span className="ai-badge">
              OpenAI
            </span>

          </div>

          <div className="chat-card">

            <div className="chat-intro">

              <div className="assistant-icon">
                ✦
              </div>

              <div>
                <strong>
                  Asistente CDMX Bus ETA
                </strong>

                <p>
                  Pregunta por las unidades, próximas paradas
                  o tiempos estimados de la ruta seleccionada.
                </p>
              </div>

            </div>

            {selectedRoute ? (

              <div className="chat-route-context">
                Consultando contexto de la ruta{" "}

                <strong>
                  {selectedRoute}
                </strong>
              </div>

            ) : (

              <div className="chat-route-context warning">
                Selecciona una ruta para obtener respuestas
                basadas en información en tiempo real.
              </div>

            )}

            <div className="chat-input-row">

              <input
                type="text"
                value={chatMessage}
                onChange={(event) =>
                  setChatMessage(event.target.value)
                }
                onKeyDown={(event) => {
                  if (
                    event.key === "Enter" &&
                    !chatLoading
                  ) {
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
                {chatLoading
                  ? "Consultando..."
                  : "Preguntar"}
              </button>

            </div>

            {chatError && (
              <div className="chat-error">
                {chatError}
              </div>
            )}

            {chatAnswer && (
              <div className="chat-answer">

                <div className="assistant-icon small">
                  ✦
                </div>

                <div>

                  <strong>
                    Respuesta del asistente
                  </strong>

                  <p>
                    {chatAnswer}
                  </p>

                  <span className="chat-disclaimer">
                    Los tiempos mostrados son estimaciones
                    generadas por el modelo ML del proyecto.
                  </span>

                </div>

              </div>
            )}

          </div>

        </section>

      </main>
    </div>
  );
}

export default App;