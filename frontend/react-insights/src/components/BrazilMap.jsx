import { useLayoutEffect, useRef, useEffect } from 'react';
import * as am5 from '@amcharts/amcharts5';
import * as am5map from '@amcharts/amcharts5/map';
import am5themes_Animated from '@amcharts/amcharts5/themes/Animated';
import am5geodata_brazilLow from '@amcharts/amcharts5-geodata/brazilLow';
import { unitsData, getUnitName } from '../data/unitsData';
import InfoTooltip from './InfoTooltip';

const stateToUnits = {
  'BR-PR': ['CTB', 'DGT CTB', 'DGT CON', 'FOZ', 'LDB'],
  'BR-SC': ['CCV'],
  'BR-RS': [],
  'BR-SP': ['SAO'],
  'BR-MG': ['MGF', 'DGT MGF'],
  'BR-MS': ['CGR'],
  'BR-MT': ['CBA'],
  'BR-BA': ['SSA'],
  'BR-SE': ['AJU'],
};

const unitCoords = {
  'CTB': { latitude: -25.4284, longitude: -49.2733 },
  'DGT CTB': { latitude: -25.45, longitude: -49.15 },
  'DGT CON': { latitude: -24.95, longitude: -51.5 },
  'FOZ': { latitude: -25.5163, longitude: -54.5854 },
  'LDB': { latitude: -23.3045, longitude: -51.1696 },
  'CCV': { latitude: -26.9034, longitude: -49.0792 },
  'SAO': { latitude: -23.5505, longitude: -46.6333 },
  'MGF': { latitude: -23.4273, longitude: -51.9375 },
  'DGT MGF': { latitude: -23.35, longitude: -51.85 },
  'CGR': { latitude: -20.4697, longitude: -54.6201 },
  'CBA': { latitude: -15.601, longitude: -56.0974 },
  'SSA': { latitude: -12.9714, longitude: -38.5014 },
  'AJU': { latitude: -10.9472, longitude: -37.0731 },
};

export default function BrazilMap({ unitVolumes, hoveredUnit, onHover }) {
  const chartRef = useRef(null);
  const rootRef = useRef(null);
  const pointSeriesRef = useRef(null);

  useLayoutEffect(() => {
    const root = am5.Root.new(chartRef.current);
    rootRef.current = root;

    root.setThemes([am5themes_Animated.new(root)]);

    const chart = root.container.children.push(
      am5map.MapChart.new(root, {
        panX: 'none',
        panY: 'none',
        wheelY: 'none',
        projection: am5map.geoMercator(),
        homeGeoPoint: { latitude: -14, longitude: -53 },
        homeZoomLevel: 1,
      })
    );

    const polygonSeries = chart.series.push(
      am5map.MapPolygonSeries.new(root, {
        geoJSON: am5geodata_brazilLow,
        valueField: 'value',
        calculateAggregates: true,
      })
    );

    polygonSeries.mapPolygons.template.setAll({
      tooltipText: '{name}',
      interactive: true,
      fill: am5.color(0xCFE3DA),
      stroke: am5.color(0xffffff),
      strokeWidth: 1,
    });

    polygonSeries.mapPolygons.template.states.create('hover', {
      fill: am5.color(0xa8c9b8),
    });

    polygonSeries.set('heatRules', [
      {
        target: polygonSeries.mapPolygons.template,
        dataField: 'value',
        min: am5.color(0xCFE3DA),
        max: am5.color(0x772B21),
        key: 'fill',
      },
    ]);

    const stateData = [];
    Object.entries(stateToUnits).forEach(([stateId, units]) => {
      const totalVolume = units.reduce((sum, u) => sum + (unitVolumes?.[u] || 0), 0);
      stateData.push({ id: stateId, value: totalVolume });
    });

    am5geodata_brazilLow.features.forEach((feature) => {
      if (!stateData.find((s) => s.id === feature.id)) {
        stateData.push({ id: feature.id, value: 0 });
      }
    });

    polygonSeries.data.setAll(stateData);

    const pointSeries = chart.series.push(
      am5map.MapPointSeries.new(root, {})
    );
    pointSeriesRef.current = pointSeries;

    pointSeries.bullets.push(function (root, series, dataItem) {
      const volume = dataItem.dataContext.volume || 0;
      const maxVolume = Math.max(...Object.values(unitVolumes || {}), 1);
      const normalized = volume / maxVolume;
      const size = 8 + normalized * 12;

      let color = am5.color(0xe5dcd7);
      if (volume > 0) {
        if (normalized > 0.7) color = am5.color(0x10b981);
        else if (normalized > 0.4) color = am5.color(0xf59e0b);
        else color = am5.color(0x6b8e23);
      }

      const container = am5.Container.new(root, {});

      const circle = container.children.push(
        am5.Circle.new(root, {
          radius: size,
          fill: color,
          stroke: am5.color(0xffffff),
          strokeWidth: 2,
          tooltipText: `{sigla}\n{nome}\n{volume} interações`,
          cursorOverStyle: 'pointer',
        })
      );

      circle.events.on('pointerover', function () {
        onHover(dataItem.dataContext.sigla);
      });

      circle.events.on('pointerout', function () {
        onHover(null);
      });

      const label = container.children.push(
        am5.Label.new(root, {
          text: dataItem.dataContext.sigla,
          fill: am5.color(0x221B19),
          fontSize: 10,
          fontWeight: '600',
          centerX: am5.percent(50),
          centerY: am5.percent(50),
          dy: -size - 8,
        })
      );

      return am5.Bullet.new(root, {
        sprite: container,
      });
    });

    const pointData = unitsData.map((unit) => ({
      geometry: {
        type: 'Point',
        coordinates: [unitCoords[unit.sigla]?.longitude || 0, unitCoords[unit.sigla]?.latitude || 0],
      },
      sigla: unit.sigla,
      nome: getUnitName(unit.sigla),
      volume: unitVolumes?.[unit.sigla] || 0,
    }));

    pointSeries.data.setAll(pointData);

    return () => {
      root.dispose();
    };
  }, []);

  useEffect(() => {
    if (!rootRef.current || !pointSeriesRef.current) return;

    const pointData = unitsData.map((unit) => ({
      geometry: {
        type: 'Point',
        coordinates: [unitCoords[unit.sigla]?.longitude || 0, unitCoords[unit.sigla]?.latitude || 0],
      },
      sigla: unit.sigla,
      nome: getUnitName(unit.sigla),
      volume: unitVolumes?.[unit.sigla] || 0,
    }));

    pointSeriesRef.current.data.setAll(pointData);
  }, [unitVolumes]);

  useEffect(() => {
    if (!pointSeriesRef.current) return;

    pointSeriesRef.current.dataItems.forEach((dataItem) => {
      const bullet = dataItem.bullets?.[0];
      if (bullet) {
        const container = bullet.get('sprite');
        if (container) {
          const circle = container.children.getIndex(0);
          if (circle) {
            const isHovered = dataItem.dataContext.sigla === hoveredUnit;
            circle.animate({
              key: 'scale',
              to: isHovered ? 1.3 : 1,
              duration: 200,
            });
            if (isHovered) {
              circle.set('stroke', am5.color(0x772B21));
              circle.set('strokeWidth', 3);
            } else {
              circle.set('stroke', am5.color(0xffffff));
              circle.set('strokeWidth', 2);
            }
          }
        }
      }
    });
  }, [hoveredUnit]);

  return (
    <div className="bg-white rounded-xl border border-border p-5 shadow-card h-full">
      <div className="flex items-center mb-4">
        <h3 className="text-base font-semibold text-foreground">Mapa de Calor das Unidades</h3>
        <InfoTooltip text="Visualização geográfica das unidades. O tamanho e cor dos pontos indicam o volume de interações. Estados em tons mais escuros têm maior atividade." />
      </div>
      <div ref={chartRef} style={{ width: '100%', height: '400px' }} />
    </div>
  );
}
