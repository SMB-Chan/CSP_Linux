using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

class PressureProbe
{
    [DllImport("wintab32.dll", EntryPoint="WTInfoA")]
    static extern uint WTInfo(uint category, uint index, IntPtr data);
    [DllImport("wintab32.dll", EntryPoint="WTOpenA")]
    static extern IntPtr WTOpen(IntPtr window, IntPtr context, bool enable);
    [DllImport("wintab32.dll")]
    static extern int WTPacketsGet(IntPtr context, int count, IntPtr data);
    [DllImport("wintab32.dll")]
    static extern bool WTClose(IntPtr context);

    [STAThread]
    static int Main()
    {
        using (Form form = new Form())
        {
            IntPtr window = form.Handle;
            IntPtr lc = Marshal.AllocHGlobal(512);
            IntPtr packets = Marshal.AllocHGlobal(16 * 64);
            IntPtr context = IntPtr.Zero;
            try
            {
                if (WTInfo(4, 0, lc) == 0) throw new Exception("No Wintab context");
                Marshal.WriteInt32(lc, 40, 4); // CXO_MESSAGES
                Marshal.WriteInt32(lc, 52, 0x7ff0);
                Marshal.WriteInt32(lc, 64, 0x5c0); // buttons, x, y, pressure
                Marshal.WriteInt32(lc, 68, 0);
                Marshal.WriteInt32(lc, 72, 0x5c0);
                Marshal.WriteInt32(lc, 76, -1);
                Marshal.WriteInt32(lc, 80, -1);
                context = WTOpen(window, lc, true);
                if (context == IntPtr.Zero) throw new Exception("WTOpen failed");
                Console.WriteLine("READY hwnd="+window+" context="+context);
                HashSet<int> pressures = new HashSet<int>();
                int count = 0;
                DateTime deadline = DateTime.UtcNow.AddSeconds(10);
                while (DateTime.UtcNow < deadline)
                {
                    Application.DoEvents();
                    int n = WTPacketsGet(context, 64, packets);
                    for (int i = 0; i < n; i++)
                    {
                        int p = Marshal.ReadInt32(packets, i * 16 + 12);
                        pressures.Add(p);
                        count++;
                    }
                    if (pressures.Contains(0) && pressures.Contains(4096) && pressures.Contains(16384) && pressures.Contains(32767))
                    {
                        Console.WriteLine("PASS packets="+count+" distinctPressure="+pressures.Count+" values=0,4096,16384,32767");
                        return 0;
                    }
                    Thread.Sleep(10);
                }
                Console.WriteLine("FAIL packets="+count+" pressures="+String.Join(",", pressures));
                return 1;
            }
            finally
            {
                if (context != IntPtr.Zero) WTClose(context);
                Marshal.FreeHGlobal(lc);
                Marshal.FreeHGlobal(packets);
            }
        }
    }
}
