import { useLayoutEffect, useRef, useEffect } from 'react';
import * as am5 from '@amcharts/amcharts5';
import * as am5percent from '@amcharts/amcharts5/percent';
import am5themes_Animated from '@amcharts/amcharts5/themes/Animated';

const COLORS = [
  0x772B21,
  0x10b981,
  0xf59e0b,
  0x6b8e23,
  0xdc7f37,
  0x8b4513,
  0x381811,
  0xAC3631,
  0x3b82f6,
  0x8b5cf6,
  0xCFE3DA,
  0x5a4f4c,
];

export default function SemiCirclePieChart({ title, data, tooltip }) {
  const chartRef = useRef(null);
  const rootRef = useRef(null);
  const seriesRef = useRef(null);

  useLayoutEffect(() => {
    const root = am5.Root.new(chartRef.current);
    rootRef.current = root;

    root.setThemes([am5themes_Animated.new(root)]);

    const chart = root.container.children.push(
      am5percent.PieChart.new(root, {
        startAngle: 180,
        endAngle: 360,
        layout: root.verticalLayout,
        innerRadius: am5.percent(50),
      })
    );

    const series = chart.series.push(
      am5percent.PieSeries.new(root, {
        startAngle: 180,
        endAngle: 360,
        valueField: 'value',
        categoryField: 'category',
        alignLabels: false,
      })
    );
    seriesRef.current = series;

    series.states.create('hidden', {
      startAngle: 180,
      endAngle: 180,
    });

    series.slices.template.setAll({
      cornerRadius: 5,
      templateField: 'settings',
      tooltipText: '{category}: {value}',
    });

    series.slices.template.states.create('hover', { scale: 1.05 });
    series.slices.template.states.create('active', { shiftRadius: 0 });

    series.ticks.template.setAll({
      forceHidden: true,
    });

    series.labels.template.setAll({
      forceHidden: true,
    });

    const legend = chart.children.push(
      am5.Legend.new(root, {
        centerX: am5.percent(50),
        x: am5.percent(50),
        marginTop: 15,
        marginBottom: 15,
      })
    );

    legend.labels.template.setAll({
      fontSize: 11,
      fill: am5.color(0x5a4f4c),
    });

    legend.valueLabels.template.setAll({
      fontSize: 11,
      fill: am5.color(0x221B19),
    });

    legend.data.setAll(series.dataItems);

    series.appear(1000, 100);

    return () => {
      root.dispose();
    };
  }, []);

  useEffect(() => {
    if (!seriesRef.current || !data || data.length === 0) return;

    const chartData = data.map((item, index) => ({
      category: item.label || item.category,
      value: item.value || item.count,
      settings: { fill: am5.color(COLORS[index % COLORS.length]) },
    }));

    seriesRef.current.data.setAll(chartData);

    const chart = seriesRef.current.chart;
    if (chart) {
      const legend = chart.children.values.find((c) => c.className === 'Legend');
      if (legend) {
        legend.data.setAll(seriesRef.current.dataItems);
      }
    }
  }, [data]);

  return (
    <div className="bg-white rounded-xl border border-border p-5 shadow-card h-full">
      <div className="flex items-center mb-2">
        <h3 className="text-base font-semibold text-foreground">{title}</h3>
        {tooltip && (
          <div className="ml-2 relative group">
            <svg className="w-4 h-4 text-muted cursor-help" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div className="absolute left-1/2 -translate-x-1/2 bottom-full mb-2 px-3 py-2 bg-gray-900 text-white text-xs rounded-lg opacity-0 invisible group-hover:opacity-100 group-hover:visible transition-all z-50 w-64 text-center">
              {tooltip}
            </div>
          </div>
        )}
      </div>
      <div ref={chartRef} style={{ width: '100%', height: '280px' }} />
    </div>
  );
}
