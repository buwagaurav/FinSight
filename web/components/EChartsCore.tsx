"use client";

// Only the parts of ECharts FinSight draws with. The full library is ~1.1 MB of JavaScript; registering these
// pieces keeps the chart code a fraction of that. Add a chart or component here before using it in an option.
import ReactEChartsCore from "echarts-for-react/lib/core";
import { BarChart, CandlestickChart, LineChart, ScatterChart } from "echarts/charts";
import { AxisPointerComponent, DataZoomInsideComponent, GridComponent, LegendComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { SVGRenderer } from "echarts/renderers";
import type { ComponentProps } from "react";

echarts.use([LineChart, BarChart, CandlestickChart, ScatterChart, GridComponent, TooltipComponent, LegendComponent,
  AxisPointerComponent, DataZoomInsideComponent, SVGRenderer]);

export default function EChartsCore(props: Omit<ComponentProps<typeof ReactEChartsCore>, "echarts">) {
  return <ReactEChartsCore echarts={echarts} {...props} />;
}
