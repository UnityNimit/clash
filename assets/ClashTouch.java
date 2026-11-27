import android.os.SystemClock;
import android.view.InputDevice;
import android.view.InputEvent;
import android.view.KeyEvent;
import android.view.MotionEvent;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.lang.reflect.Method;

public class ClashTouch {
    private static Object inputMgr;
    private static Method injectMethod;

    private static void initInput() throws Exception {
        try {
            Class<?> img = Class.forName("android.hardware.input.InputManagerGlobal");
            inputMgr = img.getMethod("getInstance").invoke(null);
            injectMethod = img.getMethod("injectInputEvent", InputEvent.class, int.class);
            return;
        } catch (Throwable ignored) {
        }
        Class<?> im = Class.forName("android.hardware.input.InputManager");
        inputMgr = im.getMethod("getInstance").invoke(null);
        injectMethod = im.getMethod("injectInputEvent", InputEvent.class, int.class);
    }

    private static void inject(MotionEvent ev) throws Exception {
        try {
            // INJECT_INPUT_EVENT_MODE_WAIT_FOR_FINISH = 2
            injectMethod.invoke(inputMgr, ev, 2);
        } finally {
            ev.recycle();
        }
    }

    private static MotionEvent.PointerProperties makeProp(int id) {
        MotionEvent.PointerProperties p = new MotionEvent.PointerProperties();
        p.id = id;
        p.toolType = MotionEvent.TOOL_TYPE_FINGER;
        return p;
    }

    private static MotionEvent.PointerCoords makeCoord(float x, float y) {
        MotionEvent.PointerCoords c = new MotionEvent.PointerCoords();
        c.x = x;
        c.y = y;
        c.pressure = 1.0f;
        c.size = 1.0f;
        return c;
    }

    private static void safeCancel(long downTime, MotionEvent.PointerProperties[] props,
                                   MotionEvent.PointerCoords[] coords, int count) {
        try {
            long now = SystemClock.uptimeMillis();
            inject(MotionEvent.obtain(downTime, now, MotionEvent.ACTION_CANCEL,
                    count, props, coords, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
        } catch (Throwable ignored) {
        }
    }

    private static void doTap(float x, float y, long holdMs) throws Exception {
        long downTime = SystemClock.uptimeMillis();
        MotionEvent.PointerProperties[] props = { makeProp(0) };
        MotionEvent.PointerCoords[] coords = { makeCoord(x, y) };
        boolean ptr1Down = false;

        try {
            inject(MotionEvent.obtain(downTime, downTime, MotionEvent.ACTION_DOWN,
                    1, props, coords, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
            ptr1Down = true;
            if (holdMs > 0) {
                Thread.sleep(holdMs);
            }
            long upTime = SystemClock.uptimeMillis();
            inject(MotionEvent.obtain(downTime, upTime, MotionEvent.ACTION_UP,
                    1, props, coords, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
            ptr1Down = false;
        } finally {
            if (ptr1Down) {
                safeCancel(downTime, props, coords, 1);
            }
        }
    }

    private static void doSwipe(float x1, float y1, float x2, float y2, long durationMs, int steps) throws Exception {
        if (steps < 2) steps = 2;
        long downTime = SystemClock.uptimeMillis();
        MotionEvent.PointerProperties[] props = { makeProp(0) };
        MotionEvent.PointerCoords[] coords = { makeCoord(x1, y1) };
        boolean ptr1Down = false;

        try {
            inject(MotionEvent.obtain(downTime, downTime, MotionEvent.ACTION_DOWN,
                    1, props, coords, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
            ptr1Down = true;

            long stepSleep = Math.max(4, durationMs / steps);
            for (int i = 1; i <= steps; i++) {
                Thread.sleep(stepSleep);
                float t = (float) i / (float) steps;
                coords[0].x = x1 + (x2 - x1) * t;
                coords[0].y = y1 + (y2 - y1) * t;
                long now = SystemClock.uptimeMillis();
                inject(MotionEvent.obtain(downTime, now, MotionEvent.ACTION_MOVE,
                        1, props, coords, 0, 0, 1.0f, 1.0f, 0, 0,
                        InputDevice.SOURCE_TOUCHSCREEN, 0));
            }

            long upTime = SystemClock.uptimeMillis();
            coords[0].x = x2;
            coords[0].y = y2;
            inject(MotionEvent.obtain(downTime, upTime, MotionEvent.ACTION_UP,
                    1, props, coords, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
            ptr1Down = false;
        } finally {
            if (ptr1Down) {
                safeCancel(downTime, props, coords, 1);
            }
        }
    }

    private static void doPinch(float x1s, float y1s, float x1e, float y1e,
                                float x2s, float y2s, float x2e, float y2e,
                                long durationMs, int steps) throws Exception {
        if (steps < 2) steps = 2;
        long downTime = SystemClock.uptimeMillis();
        MotionEvent.PointerProperties[] props1 = { makeProp(0) };
        MotionEvent.PointerCoords[] coords1 = { makeCoord(x1s, y1s) };
        MotionEvent.PointerProperties[] props2 = { makeProp(0), makeProp(1) };
        MotionEvent.PointerCoords[] coords2 = { makeCoord(x1s, y1s), makeCoord(x2s, y2s) };
        boolean ptr1Down = false;
        boolean ptr2Down = false;

        try {
            inject(MotionEvent.obtain(downTime, downTime, MotionEvent.ACTION_DOWN,
                    1, props1, coords1, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
            ptr1Down = true;
            Thread.sleep(2);

            long now = SystemClock.uptimeMillis();
            int actionPtrDown = MotionEvent.ACTION_POINTER_DOWN | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT);
            inject(MotionEvent.obtain(downTime, now, actionPtrDown,
                    2, props2, coords2, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
            ptr2Down = true;

            long stepSleep = Math.max(6, durationMs / steps);
            for (int i = 1; i <= steps; i++) {
                Thread.sleep(stepSleep);
                float t = (float) i / (float) steps;
                coords2[0].x = x1s + (x1e - x1s) * t;
                coords2[0].y = y1s + (y1e - y1s) * t;
                coords2[1].x = x2s + (x2e - x2s) * t;
                coords2[1].y = y2s + (y2e - y2s) * t;
                now = SystemClock.uptimeMillis();
                inject(MotionEvent.obtain(downTime, now, MotionEvent.ACTION_MOVE,
                        2, props2, coords2, 0, 0, 1.0f, 1.0f, 0, 0,
                        InputDevice.SOURCE_TOUCHSCREEN, 0));
            }
            // Let one game render frame consume the final pinch distance before lifting pointers
            Thread.sleep(12);

            now = SystemClock.uptimeMillis();
            int actionPtrUp = MotionEvent.ACTION_POINTER_UP | (1 << MotionEvent.ACTION_POINTER_INDEX_SHIFT);
            inject(MotionEvent.obtain(downTime, now, actionPtrUp,
                    2, props2, coords2, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
            ptr2Down = false;
            Thread.sleep(4);

            now = SystemClock.uptimeMillis();
            coords1[0].x = x1e;
            coords1[0].y = y1e;
            inject(MotionEvent.obtain(downTime, now, MotionEvent.ACTION_UP,
                    1, props1, coords1, 0, 0, 1.0f, 1.0f, 0, 0,
                    InputDevice.SOURCE_TOUCHSCREEN, 0));
            ptr1Down = false;
        } finally {
            if (ptr2Down) {
                safeCancel(downTime, props2, coords2, 2);
            } else if (ptr1Down) {
                safeCancel(downTime, props1, coords1, 1);
            }
        }
    }

    private static void doKey(int keyCode) throws Exception {
        long now = SystemClock.uptimeMillis();
        KeyEvent down = new KeyEvent(now, now, KeyEvent.ACTION_DOWN, keyCode, 0, 0,
                -1, 0, 0, InputDevice.SOURCE_KEYBOARD);
        KeyEvent up = new KeyEvent(now, now, KeyEvent.ACTION_UP, keyCode, 0, 0,
                -1, 0, 0, InputDevice.SOURCE_KEYBOARD);
        injectMethod.invoke(inputMgr, down, 2);
        injectMethod.invoke(inputMgr, up, 2);
    }

    public static void main(String[] args) throws Exception {
        initInput();
        System.out.println("READY");
        System.out.flush();
        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
        String line;
        while ((line = br.readLine()) != null) {
            line = line.trim();
            if (line.isEmpty()) continue;
            if ("quit".equals(line)) break;
            try {
                String[] p = line.split("\\s+");
                String cmd = p[0];
                if ("ping".equals(cmd)) {
                    System.out.println("OK");
                } else if ("tap".equals(cmd) && p.length >= 3) {
                    float x = Float.parseFloat(p[1]);
                    float y = Float.parseFloat(p[2]);
                    long hold = p.length >= 4 ? Long.parseLong(p[3]) : 18L;
                    doTap(x, y, hold);
                    System.out.println("OK");
                } else if ("swipe".equals(cmd) && p.length >= 6) {
                    float x1 = Float.parseFloat(p[1]);
                    float y1 = Float.parseFloat(p[2]);
                    float x2 = Float.parseFloat(p[3]);
                    float y2 = Float.parseFloat(p[4]);
                    long dur = Long.parseLong(p[5]);
                    int steps = p.length >= 7 ? Integer.parseInt(p[6]) : 22;
                    doSwipe(x1, y1, x2, y2, dur, steps);
                    System.out.println("OK");
                } else if ("pinch".equals(cmd) && p.length >= 10) {
                    float x1s = Float.parseFloat(p[1]);
                    float y1s = Float.parseFloat(p[2]);
                    float x1e = Float.parseFloat(p[3]);
                    float y1e = Float.parseFloat(p[4]);
                    float x2s = Float.parseFloat(p[5]);
                    float y2s = Float.parseFloat(p[6]);
                    float x2e = Float.parseFloat(p[7]);
                    float y2e = Float.parseFloat(p[8]);
                    long dur = Long.parseLong(p[9]);
                    int steps = p.length >= 11 ? Integer.parseInt(p[10]) : 24;
                    doPinch(x1s, y1s, x1e, y1e, x2s, y2s, x2e, y2e, dur, steps);
                    System.out.println("OK");
                } else if ("key".equals(cmd) && p.length >= 2) {
                    int code = Integer.parseInt(p[1]);
                    doKey(code);
                    System.out.println("OK");
                } else {
                    System.out.println("ERR unknown_cmd");
                }
            } catch (Throwable t) {
                System.out.println("ERR " + t.getClass().getSimpleName() + ": " + t.getMessage());
            }
            System.out.flush();
        }
    }
}
