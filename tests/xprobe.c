#define _POSIX_C_SOURCE 200809L
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/cursorfont.h>
#include <X11/extensions/XShm.h>
#include <X11/extensions/Xfixes.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#include <unistd.h>

#define RED   0xdf4b69UL
#define GREEN 0x40ce9bUL
#define BLUE  0x29435eUL

static int scene(Display *display, Window root) {
    unsigned width = 160, height = 104;
    XSetWindowBackground(display, root, BLUE);
    XClearWindow(display, root);
    Window win = XCreateSimpleWindow(display, root, 44, 40, width, height, 0, 0, RED);
    XStoreName(display, win, "X11 QA fixture");
    XMapWindow(display, win);

    Cursor cursor = XCreateFontCursor(display, XC_crosshair);
    XDefineCursor(display, win, cursor);
    XDefineCursor(display, root, cursor);
    XWarpPointer(display, None, win, 0, 0, 0, 0, 27, 25);
    GC gc = XCreateGC(display, win, 0, NULL);
    XSync(display, False);
    printf("%lu\n", (unsigned long)win);
    fflush(stdout);

    struct pollfd control = {STDIN_FILENO, POLLIN, 0};
    for (unsigned tick = 0;; tick++) {
        if (poll(&control, 1, 45) < 0)
            return 1;
        if (control.revents & (POLLIN | POLLHUP)) {
            char command;
            if (read(STDIN_FILENO, &command, 1) != 1)
                break;
            switch (command) {
            case 'f':
                width = 320; height = 240;
                XMoveResizeWindow(display, win, 0, 0, width, height);
                break;
            case 's':
                width = 160; height = 104;
                XMoveResizeWindow(display, win, 44, 40, width, height);
                break;
            case 'h': XUnmapWindow(display, win); break;
            case 'm': XMapWindow(display, win); break;
            }
        }
        XSetForeground(display, gc, tick / 4 % 2 ? GREEN : RED);
        XFillRectangle(display, win, gc, 0, 0, width, height);
        XSetForeground(display, gc, 0xf6e068);
        XFillRectangle(display, win, gc, (tick * 5) % (width - 28), height / 3, 28, 27);
        XSync(display, False);
    }
    XFreeCursor(display, cursor);
    XFreeGC(display, gc);
    XDestroyWindow(display, win);
    return 0;
}

static void report_image(XImage *image) {
    size_t nonblack = 0, known_colors = 0;
    for (int y = 0; y < image->height; y++) {
        for (int x = 0; x < image->width; x++) {
            unsigned long rgb = XGetPixel(image, x, y) & 0xffffff;
            nonblack += rgb != 0;
            known_colors += rgb == RED || rgb == GREEN || rgb == BLUE;
        }
    }
    printf("{\"width\":%d,\"height\":%d,\"total\":%zu,\"nonblack\":%zu,\"fixture\":%zu}\n",
           image->width, image->height, (size_t)image->width * image->height, nonblack, known_colors);
}

static int sample_shm(Display *display, Window win, const XWindowAttributes *attr) {
    if (!XShmQueryExtension(display))
        return 1;
    XShmSegmentInfo shm = {0};
    XImage *image = XShmCreateImage(display, attr->visual, attr->depth, ZPixmap, NULL, &shm,
                                    attr->width, attr->height);
    if (!image)
        return 1;

    int status = 1;
    size_t size = (size_t)image->bytes_per_line * image->height;
    int id = shmget(IPC_PRIVATE, size, IPC_CREAT | 0600);
    if (id < 0)
        goto cleanup;
    shm.shmid = id;
    shm.shmaddr = shmat(id, NULL, 0);
    if (shm.shmaddr == (char *)-1) {
        shmctl(id, IPC_RMID, NULL);
        goto cleanup;
    }

    /* Linux permits the X server to attach while this marked segment remains mapped. */
    if (shmctl(id, IPC_RMID, NULL) < 0)
        goto detach;
    image->data = shm.shmaddr;
    memset(image->data, 0xad, size);
    shm.readOnly = False;
    if (XShmAttach(display, &shm)) {
        XSync(display, False);
        if (XShmGetImage(display, win, image, 0, 0, AllPlanes)) {
            report_image(image);
            status = 0;
        }
        XShmDetach(display, &shm);
        XSync(display, False);
    }
detach:
    image->data = NULL;
    shmdt(shm.shmaddr);
cleanup:
    XDestroyImage(image);
    return status;
}

static int sample(Display *display, Window win, int use_shm) {
    XWindowAttributes attr;
    if (!XGetWindowAttributes(display, win, &attr))
        return 1;
    if (use_shm)
        return sample_shm(display, win, &attr);

    XImage *image = XGetImage(display, win, 0, 0, attr.width, attr.height, AllPlanes, ZPixmap);
    if (!image)
        return 1;
    report_image(image);
    XDestroyImage(image);
    return 0;
}

static int sample_cursor(Display *display) {
    XFixesCursorImage *cursor = XFixesGetCursorImage(display);
    if (!cursor)
        return 1;
    size_t nonzero = 0;
    for (size_t i = 0; i < (size_t)cursor->width * cursor->height; ++i)
        nonzero += cursor->pixels[i] != 0;
    printf("{\"width\":%u,\"height\":%u,\"nonzero\":%zu}\n", cursor->width, cursor->height, nonzero);
    XFree(cursor);
    return 0;
}

int main(int argc, char **argv) {
    if (!getenv("X11_QA_ISOLATED"))
        return 1;
    Display *display = XOpenDisplay(NULL);
    if (!display)
        return 1;
    Window root = DefaultRootWindow(display);
    int status = 1;
    if (argc == 2 && strcmp(argv[1], "cursor") == 0)
        status = sample_cursor(display);
    else if (argc == 2 && strcmp(argv[1], "scene") == 0)
        status = scene(display, root);
    else if (argc == 3 && (strcmp(argv[1], "shm") == 0 || strcmp(argv[1], "core") == 0)) {
        Window win = strcmp(argv[2], "root") == 0 ? root : strtoul(argv[2], NULL, 0);
        status = sample(display, win, strcmp(argv[1], "shm") == 0);
    }
    XCloseDisplay(display);
    return status;
}
