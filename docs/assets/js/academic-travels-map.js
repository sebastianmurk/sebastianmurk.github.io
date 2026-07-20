(function () {
  "use strict";

  const root = document.querySelector("[data-travel-map]");
  if (!root) return;

  const mapElement = document.getElementById("travels-map");
  const filterContainer = document.getElementById("travels-year-filters");
  const eventList = document.getElementById("travels-event-list");
  const resultSummary = document.getElementById("travels-result-summary");
  const listCount = document.getElementById("travels-list-count");
  const resetButton = document.getElementById("travels-reset-map");
  const gestureToggle = document.getElementById("travels-map-gesture-toggle");
  const mapHelp = document.getElementById("travels-map-help");
  const errorMessage = document.getElementById("travels-error");
  const mapTilerKeyPlaceholder = "PASTE_YOUR_PROTECTED_MAPTILER_KEY_HERE";
  const allowedContributionTypes = new Set(["Talk", "Seminar talk", "Poster"]);

  const yearColours = new Map([
  [2026, "#184e77"], // dark blue
  [2025, "#2f6fa8"], // medium blue
  [2024, "#76a9d4"], // light blue
  [2023, "#7a263a"], // dark red
  [2022, "#b23f5d"], // medium red
  [2021, "#d98da0"], // light red — reserved
  [2020, "#7a5a00"], // dark gold
  [2019, "#b38616"], // medium gold
  [2018, "#ddbe5c"], // light gold
]);

  const fallbackColours = [
    "#375a7f",
    "#6554a4",
    "#2f766d",
    "#8d4f5f",
    "#79631c",
  ];

  const prefersReducedMotion = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  ).matches;
  const usesCoarsePointer = window.matchMedia("(pointer: coarse)").matches;

  const markersById = new Map();
  const listButtonsById = new Map();
  const basemapButtonsByName = new Map();
  let map;
  let mapTilerLayer;
  let mapTilerApiKey = "";
  let markerCluster;
  let allEvents = [];
  let visibleEvents = [];
  let activeEventId = null;
  let activeYear = null;
  let activeBasemap = "streets";

  initialise().catch(showError);

  async function initialise() {
    if (!window.L || typeof window.L.markerClusterGroup !== "function") {
      throw new Error("The map library did not load.");
    }
    if (
      !window.L.maptiler ||
      typeof window.L.maptiler.maptilerLayer !== "function" ||
      !window.L.maptiler.MapStyle ||
      !window.L.maptiler.Language
    ) {
      throw new Error("The MapTiler map layer did not load.");
    }

    mapTilerApiKey = readMapTilerApiKey();

    const source = root.dataset.source;
    if (!source) throw new Error("No travel data source was configured.");

    const response = await fetch(source, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) {
      throw new Error(`Travel data request failed (${response.status}).`);
    }

    const dataset = await response.json();
    allEvents = validateDataset(dataset);

    createMap();
    createMarkers();
    createYearFilters(dataset.metadata && dataset.metadata.years);
    applyYearFilter(null);
    observeMapSize();
    map.on("popupopen", clampPopupInsideMap);

    if (usesCoarsePointer) {
      configureTouchDragging();
    }

    resetButton.addEventListener("click", function () {
      fitVisibleEvents(true);
      mapElement.focus({ preventScroll: true });
    });
  }

  function readMapTilerApiKey() {
    const apiKey = (root.dataset.maptilerKey || "").trim();
    if (!apiKey || apiKey === mapTilerKeyPlaceholder) {
      throw new Error(
        "Add the protected MapTiler API key to travels/index.qmd before previewing the map.",
      );
    }
    return apiKey;
  }

  function validateDataset(dataset) {
    if (!dataset || !Array.isArray(dataset.events) || dataset.events.length === 0) {
      throw new Error("The travel dataset contains no events.");
    }

    const ids = new Set();
    const events = dataset.events.map(function (event) {
      const location = event && event.location;
      const requiredText = [
        event && event.id,
        event && event.name,
        event && event.startDate,
        event && event.endDate,
        event && event.hostOrganization,
        event && event.venue,
        location && location.city,
        location && location.country,
      ];

      if (requiredText.some(function (value) { return !value; })) {
        throw new Error("An event is missing information required by the map.");
      }
      if (ids.has(event.id)) {
        throw new Error(`Duplicate event identifier: ${event.id}`);
      }
      if (
        !Number.isFinite(location.latitude) ||
        !Number.isFinite(location.longitude) ||
        location.latitude < -90 ||
        location.latitude > 90 ||
        location.longitude < -180 ||
        location.longitude > 180
      ) {
        throw new Error(`Invalid coordinates for ${event.name}.`);
      }
      if (!Array.isArray(event.talks) || event.talks.length === 0) {
        throw new Error(`${event.name} has no linked talks.`);
      }

      event.talks.forEach(function (talk) {
        if (
          !talk ||
          !talk.title ||
          !allowedContributionTypes.has(talk.contributionType)
        ) {
          throw new Error(`${event.name} has invalid contribution information.`);
        }
        [talk.recordingUrl, talk.slidesUrl, talk.publicationUrl]
          .filter(Boolean)
          .forEach(function (url) {
            if (typeof url !== "string" || !/^https?:\/\/\S+$/.test(url)) {
              throw new Error(`${event.name} contains an invalid contribution link.`);
            }
          });
        const hasPublicationUrl = Boolean(talk.publicationUrl);
        const hasPublicationLabel = Boolean(talk.publicationLabel);
        if (hasPublicationUrl !== hasPublicationLabel) {
          throw new Error(`${event.name} has incomplete publication information.`);
        }
        if (
          hasPublicationLabel &&
          !["Publication", "Preprint"].includes(talk.publicationLabel)
        ) {
          throw new Error(`${event.name} has an invalid publication label.`);
        }
      });

      ids.add(event.id);
      return event;
    });

    return events.sort(function (left, right) {
      return right.startDate.localeCompare(left.startDate) ||
        left.name.localeCompare(right.name);
    });
  }

  function createMap() {
    map = window.L.map(mapElement, {
      center: [18, 12],
      zoom: 2,
      minZoom: 1,
      maxZoom: 18,
      dragging: !usesCoarsePointer,
      zoomSnap: 0.5,
      zoomControl: false,
      scrollWheelZoom: true,
      worldCopyJump: true,
      preferCanvas: true,
    });

    map.attributionControl.setPrefix(
      '<a href="https://leafletjs.com/" target="_blank" rel="noopener">Leaflet</a>',
    );

    window.L.control.zoom({ position: "topleft" }).addTo(map);
    window.L.control.scale({
      position: "bottomleft",
      imperial: false,
      maxWidth: 120,
    }).addTo(map);

    mapTilerLayer = window.L.maptiler.maptilerLayer({
      apiKey: mapTilerApiKey,
      style: window.L.maptiler.MapStyle.STREETS,
      language: window.L.maptiler.Language.ENGLISH,
      maptilerLogo: true,
    }).addTo(map);
    createBasemapControl();

    markerCluster = window.L.markerClusterGroup({
      animate: !prefersReducedMotion,
      showCoverageOnHover: true,
      spiderfyOnMaxZoom: true,
      spiderfyDistanceMultiplier: 1.5,
      zoomToBoundsOnClick: true,
      maxClusterRadius: 3,
      iconCreateFunction: createClusterIcon,
    });
    markerCluster.addTo(map);
  }

  function createBasemapControl() {
    const control = window.L.control({ position: "topright" });
    control.onAdd = function () {
      const container = window.L.DomUtil.create(
        "div",
        "leaflet-bar travels-basemap-control",
      );
      container.setAttribute("role", "group");
      container.setAttribute("aria-label", "Map background");

      [
        ["streets", "Street"],
        ["satellite", "Satellite"],
      ].forEach(function (entry) {
        const name = entry[0];
        const label = entry[1];
        const button = document.createElement("button");
        button.type = "button";
        button.className = "travels-basemap-button";
        button.textContent = label;
        button.setAttribute("aria-pressed", name === activeBasemap ? "true" : "false");
        button.addEventListener("click", function () {
          setBasemap(name);
        });
        container.appendChild(button);
        basemapButtonsByName.set(name, button);
      });

      window.L.DomEvent.disableClickPropagation(container);
      window.L.DomEvent.disableScrollPropagation(container);
      return container;
    };
    control.addTo(map);
  }

  function setBasemap(name) {
    if (!mapTilerLayer || name === activeBasemap) return;

    const styles = {
      streets: window.L.maptiler.MapStyle.STREETS,
      satellite: window.L.maptiler.MapStyle.HYBRID,
    };
    const style = styles[name];
    if (!style) return;

    const sdkMap = typeof mapTilerLayer.getMaptilerSDKMap === "function"
      ? mapTilerLayer.getMaptilerSDKMap()
      : null;
    if (sdkMap && typeof sdkMap.once === "function") {
      sdkMap.once("style.load", function () {
        mapTilerLayer.setLanguage(window.L.maptiler.Language.ENGLISH);
      });
    }

    activeBasemap = name;
    mapTilerLayer.setStyle(style);
    basemapButtonsByName.forEach(function (button, buttonName) {
      button.setAttribute("aria-pressed", buttonName === name ? "true" : "false");
    });
  }

  function createMarkers() {
    allEvents.forEach(function (event) {
      const marker = window.L.marker(
        [event.location.latitude, event.location.longitude],
        {
          alt: `${event.name}, ${event.location.city}, ${event.location.country}`,
          icon: createMarkerIcon(event),
          keyboard: true,
          riseOnHover: true,
          title: event.name,
        },
      );

      marker.bindPopup(buildPopup(event), {
        autoPan: false,
        maxWidth: 390,
        minWidth: 360,
      });

      marker.on("click", function () {
        setActiveEvent(event.id, { scrollList: true });
      });

      markersById.set(event.id, marker);
    });
  }

  function clampPopupInsideMap(event) {
  const popup = event.popup;
  const popupElement = popup.getElement();

  if (!popupElement) return;

  const baseOffset = window.L.point(0, 7);
  const inset = 8;

  popup.options.offset = baseOffset;
  popupElement.classList.remove("is-map-clamped");
  popupElement.style.visibility = "hidden";
  popup.update();

  window.requestAnimationFrame(function () {
    if (!popupElement.isConnected) {
      popupElement.style.visibility = "";
      return;
    }

    const mapBounds = mapElement.getBoundingClientRect();
    const popupBounds = popupElement.getBoundingClientRect();

    let shiftX = 0;
    let shiftY = 0;

    if (popupBounds.left < mapBounds.left + inset) {
      shiftX = mapBounds.left + inset - popupBounds.left;
    } else if (popupBounds.right > mapBounds.right - inset) {
      shiftX = mapBounds.right - inset - popupBounds.right;
    }

    if (popupBounds.top < mapBounds.top + inset) {
      shiftY = mapBounds.top + inset - popupBounds.top;
    }

    const zoomControl = mapElement.querySelector(
      ".leaflet-control-zoom",
    );

    if (zoomControl) {
      const zoomBounds = zoomControl.getBoundingClientRect();

      const adjustedLeft = popupBounds.left + shiftX;
      const adjustedRight = popupBounds.right + shiftX;
      const adjustedTop = popupBounds.top + shiftY;
      const adjustedBottom = popupBounds.bottom + shiftY;

      const overlapsZoom =
        adjustedLeft < zoomBounds.right + inset &&
        adjustedRight > zoomBounds.left - inset &&
        adjustedTop < zoomBounds.bottom + inset &&
        adjustedBottom > zoomBounds.top - inset;

      if (overlapsZoom) {
        const safeLeft = zoomBounds.right + inset;
        const roomToRight =
          mapBounds.right - inset - safeLeft;

        if (popupBounds.width <= roomToRight) {
          shiftX += safeLeft - adjustedLeft;
        } else {
          shiftY += Math.max(
            0,
            zoomBounds.bottom + inset - adjustedTop,
          );
        }
      }
    }

    if (shiftX !== 0 || shiftY !== 0) {
      popup.options.offset = window.L.point(
        baseOffset.x + shiftX,
        baseOffset.y + shiftY,
      );

      popupElement.classList.add("is-map-clamped");
      popup.update();
    }

    popupElement.style.visibility = "";
  });
}

  function createMarkerIcon(event) {
    const colour = colourForYear(event.year);
    const accessibleName =
      `${event.name}, ${event.location.city}, ${event.location.country}, ${event.year}`;
    return window.L.divIcon({
      className: "travels-leaflet-marker",
      html:
        `<span class="travels-marker-dot" style="--marker-colour: ${colour}">` +
        `<span class="visually-hidden">${escapeHtml(accessibleName)}</span></span>`,
      iconAnchor: [13, 23],
      iconSize: [26, 26],
      popupAnchor: [0, -22],
    });
  }

  function createClusterIcon(cluster) {
    const childMarkers = cluster.getAllChildMarkers();
    const childYears = new Set(
      childMarkers.map(function (marker) {
        const event = eventForMarker(marker);
        return event ? event.year : null;
      }),
    );
    childYears.delete(null);

    const colour = childYears.size === 1
      ? colourForYear(Array.from(childYears)[0])
      : "#344d68";
    const count = cluster.getChildCount();

    return window.L.divIcon({
      className: "travels-cluster-icon",
      html:
        `<span class="travels-cluster" style="--cluster-colour: ${colour}">` +
        `<span aria-hidden="true">${count}</span>` +
        `<span class="visually-hidden">${count} events</span></span>`,
      iconAnchor: [19, 19],
      iconSize: [38, 38],
    });
  }

  function eventForMarker(marker) {
    for (const event of allEvents) {
      if (markersById.get(event.id) === marker) return event;
    }
    return null;
  }

  function createYearFilters(metadataYears) {
    const years = Array.isArray(metadataYears) && metadataYears.length
      ? metadataYears.slice()
      : Array.from(new Set(allEvents.map(function (event) { return event.year; })));

    years.sort(function (left, right) { return right - left; });
    filterContainer.replaceChildren();
    filterContainer.appendChild(
      makeFilterButton(null, "All", allEvents.length),
    );

    years.forEach(function (year) {
      const count = allEvents.filter(function (event) {
        return event.year === Number(year);
      }).length;
      filterContainer.appendChild(
        makeFilterButton(Number(year), String(year), count),
      );
    });
  }

  function makeFilterButton(year, label, count) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "travels-year-filter";
    button.dataset.year = year === null ? "all" : String(year);
    button.setAttribute("aria-pressed", year === null ? "true" : "false");

    if (year !== null) {
      const dot = document.createElement("span");
      dot.className = "travels-year-dot";
      dot.style.setProperty("--year-colour", colourForYear(year));
      dot.setAttribute("aria-hidden", "true");
      button.appendChild(dot);
    }

    const labelElement = document.createElement("span");
    labelElement.textContent = label;
    button.appendChild(labelElement);

    const countElement = document.createElement("span");
    countElement.className = "travels-filter-count";
    countElement.textContent = String(count);
    countElement.setAttribute("aria-hidden", "true");
    button.appendChild(countElement);

    button.setAttribute(
      "aria-label",
      year === null
        ? `Show all ${count} events`
        : `Show ${count} events from ${year}`,
    );
    button.addEventListener("click", function () {
      applyYearFilter(year);
    });
    return button;
  }

  function applyYearFilter(year) {
    activeYear = year;
    activeEventId = null;
    map.closePopup();

    visibleEvents = year === null
      ? allEvents.slice()
      : allEvents.filter(function (event) { return event.year === year; });

    markerCluster.clearLayers();
    markerCluster.addLayers(
      visibleEvents.map(function (event) { return markersById.get(event.id); }),
    );

    filterContainer.querySelectorAll(".travels-year-filter").forEach(function (button) {
      const buttonYear = button.dataset.year === "all"
        ? null
        : Number(button.dataset.year);
      const selected = buttonYear === activeYear;
      button.setAttribute("aria-pressed", selected ? "true" : "false");
    });

    renderEventList();
    updateSummary();
    fitVisibleEvents(false);
  }

  function renderEventList() {
    eventList.replaceChildren();
    listButtonsById.clear();

    visibleEvents.forEach(function (event) {
      const item = document.createElement("li");
      item.className = "travels-event-item";

      const button = document.createElement("button");
      button.type = "button";
      button.className = "travels-event-button";
      button.style.setProperty("--event-colour", colourForYear(event.year));
      button.setAttribute(
        "aria-label",
        `Show ${event.name} in ${event.location.city} on the map`,
      );

      const meta = document.createElement("span");
      meta.className = "travels-event-meta";

      const year = document.createElement("span");
      year.className = "travels-event-year";
      year.innerHTML =
        `<span class="travels-year-dot" style="--year-colour: ${colourForYear(event.year)}" ` +
        `aria-hidden="true"></span>${event.year}`;
      meta.appendChild(year);

      const date = document.createElement("span");
      date.className = "travels-event-date";
      date.textContent = formatDateRange(event.startDate, event.endDate);
      meta.appendChild(date);

      const name = document.createElement("span");
      name.className = "travels-event-name";
      name.textContent = event.name;

      const location = document.createElement("span");
      location.className = "travels-event-location";
      location.textContent = `${event.location.city}, ${event.location.country}`;

      button.append(meta, name, location);

      button.addEventListener("click", function () {
        showEventOnMap(event.id);
      });

      item.appendChild(button);
      eventList.appendChild(item);
      listButtonsById.set(event.id, button);
    });
  }

  function showEventOnMap(eventId) {
    const marker = markersById.get(eventId);
    if (!marker) return;

    setActiveEvent(eventId, { scrollList: false });
    markerCluster.zoomToShowLayer(marker, function () {
      if (activeEventId !== eventId) return;
      marker.openPopup();
      window.requestAnimationFrame(function () {
        if (activeEventId !== eventId) return;
        const popupContent = marker.getPopup().getContent();
        if (popupContent instanceof HTMLElement) {
          popupContent.focus({ preventScroll: true });
        }
      });
    });
  }

  function setActiveEvent(eventId, options) {
    activeEventId = eventId;
    listButtonsById.forEach(function (button, id) {
      const selected = id === activeEventId;
      button.classList.toggle("is-active", selected);
      if (selected) {
        button.setAttribute("aria-current", "true");
      } else {
        button.removeAttribute("aria-current");
      }
    });

    const activeButton = listButtonsById.get(eventId);
    if (activeButton && options && options.scrollList) {
      activeButton.scrollIntoView({
        behavior: prefersReducedMotion ? "auto" : "smooth",
        block: "nearest",
      });
    }
  }

  function updateSummary() {
    const eventWord = visibleEvents.length === 1 ? "event" : "events";

    const countries = new Set(
      visibleEvents.map(function (event) {
        return event.location.country;
      }),
    ).size;

    const countryWord = countries === 1 ? "country" : "countries";
    const yearText = activeYear === null ? "" : ` from ${activeYear}`;

    resultSummary.textContent =
      `Showing ${visibleEvents.length} ${eventWord}${yearText} in ` +
      `${countries} ${countryWord}.`;

    listCount.textContent = `${visibleEvents.length} ${eventWord}`;
  }

  function fitVisibleEvents(animate) {
    if (!map || visibleEvents.length === 0) return;

    window.requestAnimationFrame(function () {
      map.invalidateSize({ pan: false });
      const points = visibleEvents.map(function (event) {
        return [event.location.latitude, event.location.longitude];
      });

      if (points.length === 1) {
        map.setView(points[0], 7, {
          animate: animate && !prefersReducedMotion,
        });
        return;
      }

      map.fitBounds(window.L.latLngBounds(points), {
        animate: animate && !prefersReducedMotion,
        maxZoom: 7,
        padding: [34, 34],
      });
    });
  }

  function buildPopup(event) {
    const popup = document.createElement("article");
    popup.className = "travels-popup";
    popup.tabIndex = -1;
    popup.setAttribute("role", "region");
    popup.setAttribute("aria-label", `${event.name} event details`);

    const meta = document.createElement("p");
    meta.className = "travels-popup-meta";
    const dot = document.createElement("span");
    dot.className = "travels-year-dot";
    dot.style.setProperty("--year-colour", colourForYear(event.year));
    dot.setAttribute("aria-hidden", "true");
    meta.append(dot, document.createTextNode(`${event.year} · ${event.type}`));

    const title = document.createElement("h3");
    title.textContent = event.name;

    const dates = document.createElement("p");
    dates.className = "travels-popup-dates";
    dates.textContent = formatDateRange(event.startDate, event.endDate);

    const details = document.createElement("dl");
    details.className = "travels-popup-details";
    appendDetail(details, "Venue", event.venue);
    appendDetail(
      details,
      "Location",
      [event.location.address, formatLocation(event.location)]
        .filter(Boolean)
        .join(" · "),
    );
    appendDetail(details, "Host", event.hostOrganization);

    const talks = document.createElement("section");
    talks.className = "travels-popup-talks";
    const talksHeading = document.createElement("h4");
    talksHeading.textContent = contributionHeading(event.talks);
    const talkList = document.createElement(event.talks.length === 1 ? "div" : "ol");
    talkList.className = "travels-popup-talk-list";

    event.talks.forEach(function (talk) {
      const talkItem = document.createElement(
        event.talks.length === 1 ? "div" : "li",
      );
      talkItem.className = "travels-popup-talk";

      const talkTitle = document.createElement("p");
      talkTitle.className = "travels-popup-talk-title";
      talkTitle.textContent = talk.title;
      talkItem.appendChild(talkTitle);

      if (talk.recordingUrl || talk.slidesUrl || talk.publicationUrl) {
        const actions = document.createElement("p");
        actions.className = "travels-popup-actions";
        if (talk.recordingUrl) {
          actions.appendChild(makeExternalLink(talk.recordingUrl, "Video"));
        }
        if (talk.slidesUrl) {
          actions.appendChild(makeExternalLink(talk.slidesUrl, "Slides"));
        }
        if (talk.publicationUrl) {
          actions.appendChild(
            makeExternalLink(talk.publicationUrl, talk.publicationLabel),
          );
        }
        talkItem.appendChild(actions);
      }

      talkList.appendChild(talkItem);
    });

    talks.append(talksHeading, talkList);
    popup.append(meta, title, dates, details, talks);

    if (event.url) {
      const eventAction = document.createElement("p");
      eventAction.className = "travels-popup-event-action";
      eventAction.appendChild(makeExternalLink(event.url, "Event website ↗"));
      popup.appendChild(eventAction);
    }

    return popup;
  }

  function contributionHeading(talks) {
    const types = Array.from(
      new Set(talks.map(function (talk) { return talk.contributionType; })),
    );
    if (types.length !== 1) return "Contributions";
    if (talks.length === 1) return types[0];
    if (types[0] === "Seminar talk") return "Seminar talks";
    return `${types[0]}s`;
  }

  function appendDetail(list, label, value) {
    if (!value) return;
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = value;
    list.append(term, description);
  }

  function makeExternalLink(url, label) {
    const link = document.createElement("a");
    link.href = url;
    link.target = "_blank";
    link.rel = "noopener";
    link.textContent = label;
    return link;
  }

  function formatLocation(location) {
    const parts = [location.city];
    if (location.region && location.region !== location.city) {
      parts.push(location.region);
    }
    parts.push(location.country);
    return parts.join(", ");
  }

  function formatDateRange(startDate, endDate) {
    const start = parseIsoDate(startDate);
    const end = parseIsoDate(endDate);

    if (startDate === endDate) return formatDateObject(start);

    if (
      start.getUTCFullYear() === end.getUTCFullYear() &&
      start.getUTCMonth() === end.getUTCMonth()
    ) {
      return (
        `${start.getUTCDate()}–${end.getUTCDate()} ` +
        `${monthName(end)} ${end.getUTCFullYear()}`
      );
    }

    if (start.getUTCFullYear() === end.getUTCFullYear()) {
      return (
        `${start.getUTCDate()} ${monthName(start)} – ` +
        `${end.getUTCDate()} ${monthName(end)} ${end.getUTCFullYear()}`
      );
    }

    return `${formatDateObject(start)} – ${formatDateObject(end)}`;
  }

  function parseIsoDate(value) {
    const parts = value.split("-").map(Number);
    return new Date(Date.UTC(parts[0], parts[1] - 1, parts[2]));
  }

  function formatDateObject(date) {
    return `${date.getUTCDate()} ${monthName(date)} ${date.getUTCFullYear()}`;
  }

  function monthName(date) {
    return new Intl.DateTimeFormat("en-GB", {
      month: "long",
      timeZone: "UTC",
    }).format(date);
  }

  function colourForYear(year) {
    if (yearColours.has(Number(year))) return yearColours.get(Number(year));
    return fallbackColours[Math.abs(Number(year)) % fallbackColours.length];
  }

  function escapeHtml(value) {
    return value.replace(/[&<>"']/g, function (character) {
      return {
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#039;",
      }[character];
    });
  }

  function configureTouchDragging() {
    gestureToggle.hidden = false;
    mapHelp.textContent =
      "Select an event from the list, use the zoom controls, or enable map dragging.";

    gestureToggle.addEventListener("click", function () {
      const shouldEnable = !map.dragging.enabled();
      if (shouldEnable) {
        map.dragging.enable();
      } else {
        map.dragging.disable();
      }

      gestureToggle.setAttribute("aria-pressed", shouldEnable ? "true" : "false");
      gestureToggle.textContent = shouldEnable
        ? "Disable map dragging"
        : "Enable map dragging";
      mapHelp.textContent = shouldEnable
        ? "Drag to move the map. Disable dragging to scroll past it more easily."
        : "Select an event from the list, use the zoom controls, or enable map dragging.";
    });
  }

  function observeMapSize() {
    if ("ResizeObserver" in window) {
      const observer = new ResizeObserver(function () {
        map.invalidateSize({ pan: false });
      });
      observer.observe(mapElement);
      return;
    }

    window.addEventListener("resize", function () {
      map.invalidateSize({ pan: false });
    });
  }

  function showError(error) {
    console.error(error);
    root.classList.add("has-error");
    errorMessage.hidden = false;
    errorMessage.textContent =
      "The academic travel map could not be loaded. Please try refreshing the page.";
    resultSummary.textContent = "Map unavailable.";
  }
})();
