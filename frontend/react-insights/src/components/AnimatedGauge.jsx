import { useLayoutEffect, useRef, useEffect } from 'react';
import * as am5 from '@amcharts/amcharts5';
import * as am5xy from '@amcharts/amcharts5/xy';
import * as am5radar from '@amcharts/amcharts5/radar';
import am5themes_Animated from '@amcharts/amcharts5/themes/Animated';

export default function AnimatedGauge({ title, percentage, label, tooltip }) {
  const chartRef = useRef(null);
  const rootRef = useRef(null);
  const axisDataItemRef = useRef(null);
  const axisRange0Ref = useRef(null);
  const axisRange1Ref = useRef(null);
  const labelRef = useRef(null);

  useLayoutEffect(() => {
    const root = am5.Root.new(chartRef.current);
    rootRef.current = root;

    root.setThemes([am5themes_Animated.new(root)]);

    const chart = root.container.children.push(
      am5radar.RadarChart.new(root, {
        panX: false,
        panY: false,
        startAngle: 180,
        endAngle: 360,
      })
    );

    chart.getNumberFormatter().set('numberFormat', "#'%'");

    const axisRenderer = am5radar.AxisRendererCircular.new(root, {
      innerRadius: -40,
    });

    axisRenderer.grid.template.setAll({
      stroke: root.interfaceColors.get('background'),
      visible: true,
      strokeOpacity: 0.8,
    });

    const xAxis = chart.xAxes.push(
      am5xy.ValueAxis.new(root, {
        maxDeviation: 0,
        min: 0,
        max: 100,
        strictMinMax: true,
        renderer: axisRenderer,
      })
    );

    const axisDataItem = xAxis.makeDataItem({});
    axisDataItemRef.current = axisDataItem;

    const clockHand = am5radar.ClockHand.new(root, {
      pinRadius: 50,
      radius: am5.percent(100),
      innerRadius: 50,
      bottomWidth: 0,
      topWidth: 0,
    });

    clockHand.pin.setAll({
      fillOpacity: 0,
      strokeOpacity: 0.5,
      stroke: am5.color(0x000000),
      strokeWidth: 1,
      strokeDasharray: [2, 2],
    });

    clockHand.hand.setAll({
      fillOpacity: 0,
      strokeOpacity: 0.5,
      stroke: am5.color(0x000000),
      strokeWidth: 0.5,
    });

    const bullet = axisDataItem.set(
      'bullet',
      am5xy.AxisBullet.new(root, {
        sprite: clockHand,
      })
    );

    xAxis.createAxisRange(axisDataItem);

    const centerLabel = chart.radarContainer.children.push(
      am5.Label.new(root, {
        centerX: am5.percent(50),
        textAlign: 'center',
        centerY: am5.percent(50),
        fontSize: '2em',
        fontWeight: '600',
        fill: am5.color(0x772B21),
      })
    );
    labelRef.current = centerLabel;

    axisDataItem.set('value', 0);
    bullet.get('sprite').on('rotation', function () {
      const value = axisDataItem.get('value');
      centerLabel.set('text', Math.round(value).toString() + '%');
    });

    chart.bulletsContainer.set('mask', undefined);

    const axisRange0 = xAxis.createAxisRange(
      xAxis.makeDataItem({
        above: true,
        value: 0,
        endValue: 0,
      })
    );
    axisRange0Ref.current = axisRange0;

    axisRange0.get('axisFill').setAll({
      visible: true,
      fill: am5.color(0x10b981),
    });

    axisRange0.get('label').setAll({
      forceHidden: true,
    });

    const axisRange1 = xAxis.createAxisRange(
      xAxis.makeDataItem({
        above: true,
        value: 0,
        endValue: 100,
      })
    );
    axisRange1Ref.current = axisRange1;

    axisRange1.get('axisFill').setAll({
      visible: true,
      fill: am5.color(0xf59e0b),
    });

    axisRange1.get('label').setAll({
      forceHidden: true,
    });

    chart.appear(1000, 100);

    return () => {
      root.dispose();
    };
  }, []);

  useEffect(() => {
    if (!axisDataItemRef.current || percentage === undefined || percentage === null) return;

    const value = Math.min(100, Math.max(0, percentage));

    axisDataItemRef.current.animate({
      key: 'value',
      to: value,
      duration: 800,
      easing: am5.ease.out(am5.ease.cubic),
    });

    axisRange0Ref.current.animate({
      key: 'endValue',
      to: value,
      duration: 800,
      easing: am5.ease.out(am5.ease.cubic),
    });

    axisRange1Ref.current.animate({
      key: 'value',
      to: value,
      duration: 800,
      easing: am5.ease.out(am5.ease.cubic),
    });
  }, [percentage]);

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
      <div ref={chartRef} style={{ width: '100%', height: '220px' }} />
      {label && (
        <div className="text-center mt-2">
          <span className="text-sm text-muted">{label}</span>
        </div>
      )}
      <div className="flex justify-center gap-6 mt-3 text-xs">
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-success" />
          <span className="text-muted">IA</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-3 h-3 rounded-full bg-warning" />
          <span className="text-muted">Humano</span>
        </div>
      </div>
    </div>
  );
}
